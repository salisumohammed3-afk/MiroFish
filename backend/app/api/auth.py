"""
Authentication & Admin API routes.
Supabase handles login from the frontend SDK.
Admin creates users directly with temporary passwords.
"""

from flask import request, jsonify, g

from . import auth_bp
from ..middleware.auth import require_auth, require_admin
from ..services.supabase_client import get_supabase_admin
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.auth')


# ──────────────────────────────────────────────
# Current User
# ──────────────────────────────────────────────

@auth_bp.route('/me', methods=['GET'])
@require_auth
def get_me():
    """Get the current authenticated user's profile."""
    user = g.user
    company = None
    if user.company_id:
        sb = get_supabase_admin()
        result = sb.table("companies").select("*").eq("id", user.company_id).execute()
        if result.data:
            company = result.data[0]

    return jsonify({
        "success": True,
        "data": {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role,
            "company_id": user.company_id,
            "company": company,
            "must_change_password": user.must_change_password,
        }
    })


@auth_bp.route('/me', methods=['PATCH'])
@require_auth
def update_me():
    """Update the current user's display name."""
    data = request.get_json()
    updates = {}
    if "display_name" in data:
        updates["display_name"] = data["display_name"].strip()

    if not updates:
        return jsonify({"success": False, "error": "No fields to update"}), 400

    sb = get_supabase_admin()
    sb.table("user_profiles").update(updates).eq("id", g.user.id).execute()
    return jsonify({"success": True})


@auth_bp.route('/me/change-password', methods=['POST'])
@require_auth
def change_password():
    """Change the current user's password and clear the must_change_password flag."""
    data = request.get_json()
    new_password = data.get("new_password", "")

    if len(new_password) < 8:
        return jsonify({"success": False, "error": "Password must be at least 8 characters"}), 400

    sb = get_supabase_admin()

    try:
        sb.auth.admin.update_user_by_id(g.user.id, {"password": new_password})
    except Exception as e:
        logger.error(f"Failed to update password: {e}")
        return jsonify({"success": False, "error": "Failed to update password"}), 500

    sb.table("user_profiles").update({"must_change_password": False}).eq("id", g.user.id).execute()

    return jsonify({"success": True})


# ──────────────────────────────────────────────
# Company Management (super_admin only)
# ──────────────────────────────────────────────

@auth_bp.route('/admin/companies', methods=['GET'])
@require_admin
def list_companies():
    """List all companies."""
    sb = get_supabase_admin()
    result = sb.table("companies").select("*, user_profiles(count)").order("created_at", desc=True).execute()
    return jsonify({"success": True, "data": result.data})


@auth_bp.route('/admin/companies', methods=['POST'])
@require_admin
def create_company():
    """Create a new company."""
    data = request.get_json()
    name = data.get("name", "").strip()
    slug = data.get("slug", "").strip().lower()

    if not name or not slug:
        return jsonify({"success": False, "error": "name and slug are required"}), 400

    sb = get_supabase_admin()

    existing = sb.table("companies").select("id").eq("slug", slug).execute()
    if existing.data:
        return jsonify({"success": False, "error": f"Company with slug '{slug}' already exists"}), 409

    result = sb.table("companies").insert({
        "name": name,
        "slug": slug,
        "logo_url": data.get("logo_url"),
    }).execute()

    return jsonify({"success": True, "data": result.data[0]}), 201


@auth_bp.route('/admin/companies/<company_id>', methods=['PATCH'])
@require_admin
def update_company(company_id):
    """Update a company."""
    data = request.get_json()
    updates = {}
    if "name" in data:
        updates["name"] = data["name"].strip()
    if "logo_url" in data:
        updates["logo_url"] = data["logo_url"]

    if not updates:
        return jsonify({"success": False, "error": "No fields to update"}), 400

    sb = get_supabase_admin()
    result = sb.table("companies").update(updates).eq("id", company_id).execute()

    if not result.data:
        return jsonify({"success": False, "error": "Company not found"}), 404

    return jsonify({"success": True, "data": result.data[0]})


@auth_bp.route('/admin/companies/<company_id>', methods=['DELETE'])
@require_admin
def delete_company(company_id):
    """Delete a company."""
    sb = get_supabase_admin()
    sb.table("companies").delete().eq("id", company_id).execute()
    return jsonify({"success": True})


# ──────────────────────────────────────────────
# User Management (super_admin)
# ──────────────────────────────────────────────

@auth_bp.route('/admin/users', methods=['GET'])
@require_admin
def list_users():
    """List all users, optionally filtered by company."""
    company_id = request.args.get("company_id")
    sb = get_supabase_admin()

    query = sb.table("user_profiles").select("*, companies(name, slug)")
    if company_id:
        query = query.eq("company_id", company_id)
    result = query.order("created_at", desc=True).execute()

    return jsonify({"success": True, "data": result.data})


@auth_bp.route('/admin/users', methods=['POST'])
@require_admin
def create_user():
    """
    Create a new user directly.
    Admin provides: name, email, temporary password, company, role.
    User must change password on first login.
    """
    data = request.get_json()
    email = data.get("email", "").strip().lower()
    display_name = data.get("display_name", "").strip()
    password = data.get("password", "").strip()
    company_id = data.get("company_id")
    role = data.get("role", "member")

    if not email:
        return jsonify({"success": False, "error": "Email is required"}), 400
    if not display_name:
        return jsonify({"success": False, "error": "Name is required"}), 400
    if len(password) < 8:
        return jsonify({"success": False, "error": "Password must be at least 8 characters"}), 400
    if role not in ("admin", "member", "viewer"):
        return jsonify({"success": False, "error": "Invalid role"}), 400
    if not company_id:
        return jsonify({"success": False, "error": "Company is required"}), 400

    sb = get_supabase_admin()

    try:
        auth_result = sb.auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {"display_name": display_name},
        })
        user_id = auth_result.user.id
    except Exception as e:
        error_msg = str(e)
        if "already been registered" in error_msg or "already exists" in error_msg:
            return jsonify({"success": False, "error": "A user with this email already exists"}), 409
        logger.error(f"Failed to create auth user: {e}")
        return jsonify({"success": False, "error": f"Failed to create user: {error_msg}"}), 500

    # The handle_new_user trigger creates a profile, but we need to update it
    # with the correct company, role, and must_change_password flag
    sb.table("user_profiles").update({
        "company_id": company_id,
        "role": role,
        "display_name": display_name,
        "must_change_password": True,
    }).eq("id", str(user_id)).execute()

    logger.info(f"User created: {email} → company {company_id}, role {role}")

    return jsonify({
        "success": True,
        "data": {
            "id": str(user_id),
            "email": email,
            "display_name": display_name,
            "company_id": company_id,
            "role": role,
        }
    }), 201


@auth_bp.route('/admin/users/<user_id>', methods=['PATCH'])
@require_admin
def update_user(user_id):
    """Update a user's role, company, or active status."""
    data = request.get_json()
    updates = {}
    if "role" in data:
        if data["role"] not in ("super_admin", "admin", "member", "viewer"):
            return jsonify({"success": False, "error": "Invalid role"}), 400
        updates["role"] = data["role"]
    if "company_id" in data:
        updates["company_id"] = data["company_id"]
    if "is_active" in data:
        updates["is_active"] = bool(data["is_active"])
    if "display_name" in data:
        updates["display_name"] = data["display_name"]

    if not updates:
        return jsonify({"success": False, "error": "No fields to update"}), 400

    sb = get_supabase_admin()
    result = sb.table("user_profiles").update(updates).eq("id", user_id).execute()

    if not result.data:
        return jsonify({"success": False, "error": "User not found"}), 404

    return jsonify({"success": True, "data": result.data[0]})


@auth_bp.route('/admin/users/<user_id>/reset-password', methods=['POST'])
@require_admin
def reset_user_password(user_id):
    """Reset a user's password (admin sets a new temporary password)."""
    data = request.get_json()
    new_password = data.get("password", "").strip()

    if len(new_password) < 8:
        return jsonify({"success": False, "error": "Password must be at least 8 characters"}), 400

    sb = get_supabase_admin()

    try:
        sb.auth.admin.update_user_by_id(user_id, {"password": new_password})
    except Exception as e:
        logger.error(f"Failed to reset password: {e}")
        return jsonify({"success": False, "error": "Failed to reset password"}), 500

    sb.table("user_profiles").update({"must_change_password": True}).eq("id", user_id).execute()

    return jsonify({"success": True})
