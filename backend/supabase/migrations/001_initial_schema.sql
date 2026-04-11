-- ============================================================
-- MiroFish Multi-Tenant Schema
-- Run this in your Supabase SQL Editor (Dashboard → SQL Editor)
-- ============================================================

-- 1. Companies table
CREATE TABLE public.companies (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    logo_url TEXT,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);

CREATE INDEX idx_companies_slug ON public.companies(slug);

-- 2. User profiles (extends Supabase auth.users)
CREATE TABLE public.user_profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    company_id UUID REFERENCES public.companies(id) ON DELETE SET NULL,
    email TEXT NOT NULL,
    display_name TEXT,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('super_admin', 'admin', 'member', 'viewer')),
    is_active BOOLEAN DEFAULT true NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);

CREATE INDEX idx_user_profiles_company ON public.user_profiles(company_id);
CREATE INDEX idx_user_profiles_email ON public.user_profiles(email);

-- 3. Invitations
CREATE TABLE public.invitations (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    company_id UUID NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member', 'viewer')),
    invited_by UUID NOT NULL REFERENCES public.user_profiles(id),
    token TEXT NOT NULL UNIQUE DEFAULT encode(gen_random_bytes(32), 'hex'),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (now() + INTERVAL '7 days'),
    accepted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL
);

CREATE INDEX idx_invitations_token ON public.invitations(token);
CREATE INDEX idx_invitations_email ON public.invitations(email);
CREATE INDEX idx_invitations_company ON public.invitations(company_id);

-- 4. Project ownership (links existing project IDs to companies)
CREATE TABLE public.project_ownership (
    project_id TEXT PRIMARY KEY,
    company_id UUID NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
    created_by UUID REFERENCES public.user_profiles(id),
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL
);

CREATE INDEX idx_project_ownership_company ON public.project_ownership(company_id);

-- 5. Simulation ownership (links existing simulation IDs to companies)
CREATE TABLE public.simulation_ownership (
    simulation_id TEXT PRIMARY KEY,
    company_id UUID NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
    project_id TEXT REFERENCES public.project_ownership(project_id) ON DELETE SET NULL,
    created_by UUID REFERENCES public.user_profiles(id),
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL
);

CREATE INDEX idx_simulation_ownership_company ON public.simulation_ownership(company_id);

-- ============================================================
-- Row Level Security (RLS) Policies
-- ============================================================

ALTER TABLE public.companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.project_ownership ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.simulation_ownership ENABLE ROW LEVEL SECURITY;

-- Helper: get the current user's company_id
CREATE OR REPLACE FUNCTION public.get_my_company_id()
RETURNS UUID
LANGUAGE sql
STABLE
SECURITY DEFINER
AS $$
    SELECT company_id FROM public.user_profiles WHERE id = auth.uid();
$$;

-- Helper: check if the current user is a super_admin
CREATE OR REPLACE FUNCTION public.is_super_admin()
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.user_profiles
        WHERE id = auth.uid() AND role = 'super_admin'
    );
$$;

-- Companies: super_admin sees all, others see own company only
CREATE POLICY "Super admin sees all companies"
    ON public.companies FOR SELECT
    USING (public.is_super_admin());

CREATE POLICY "Members see own company"
    ON public.companies FOR SELECT
    USING (id = public.get_my_company_id());

CREATE POLICY "Super admin manages companies"
    ON public.companies FOR ALL
    USING (public.is_super_admin());

-- User profiles: super_admin sees all, others see same company
CREATE POLICY "Super admin sees all profiles"
    ON public.user_profiles FOR SELECT
    USING (public.is_super_admin());

CREATE POLICY "Members see own company profiles"
    ON public.user_profiles FOR SELECT
    USING (company_id = public.get_my_company_id());

CREATE POLICY "Users can update own profile"
    ON public.user_profiles FOR UPDATE
    USING (id = auth.uid());

CREATE POLICY "Super admin manages all profiles"
    ON public.user_profiles FOR ALL
    USING (public.is_super_admin());

-- Invitations: super_admin + company admins can manage
CREATE POLICY "Super admin sees all invitations"
    ON public.invitations FOR SELECT
    USING (public.is_super_admin());

CREATE POLICY "Company admins see own invitations"
    ON public.invitations FOR SELECT
    USING (company_id = public.get_my_company_id());

CREATE POLICY "Super admin manages invitations"
    ON public.invitations FOR ALL
    USING (public.is_super_admin());

CREATE POLICY "Company admins create invitations"
    ON public.invitations FOR INSERT
    WITH CHECK (
        company_id = public.get_my_company_id()
        AND EXISTS (
            SELECT 1 FROM public.user_profiles
            WHERE id = auth.uid() AND role IN ('super_admin', 'admin')
        )
    );

-- Project ownership: company-scoped
CREATE POLICY "Super admin sees all projects"
    ON public.project_ownership FOR SELECT
    USING (public.is_super_admin());

CREATE POLICY "Members see own company projects"
    ON public.project_ownership FOR SELECT
    USING (company_id = public.get_my_company_id());

CREATE POLICY "Members create projects for own company"
    ON public.project_ownership FOR INSERT
    WITH CHECK (company_id = public.get_my_company_id());

CREATE POLICY "Super admin manages all projects"
    ON public.project_ownership FOR ALL
    USING (public.is_super_admin());

-- Simulation ownership: company-scoped
CREATE POLICY "Super admin sees all simulations"
    ON public.simulation_ownership FOR SELECT
    USING (public.is_super_admin());

CREATE POLICY "Members see own company simulations"
    ON public.simulation_ownership FOR SELECT
    USING (company_id = public.get_my_company_id());

CREATE POLICY "Members create simulations for own company"
    ON public.simulation_ownership FOR INSERT
    WITH CHECK (company_id = public.get_my_company_id());

CREATE POLICY "Super admin manages all simulations"
    ON public.simulation_ownership FOR ALL
    USING (public.is_super_admin());

-- ============================================================
-- Auto-create profile on signup
-- ============================================================

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    _company_id UUID;
    _role TEXT;
    _invitation RECORD;
BEGIN
    -- Check if there's a pending invitation for this email
    SELECT * INTO _invitation
    FROM public.invitations
    WHERE email = NEW.email
      AND accepted_at IS NULL
      AND expires_at > now()
    ORDER BY created_at DESC
    LIMIT 1;

    IF _invitation IS NOT NULL THEN
        _company_id := _invitation.company_id;
        _role := _invitation.role;

        UPDATE public.invitations
        SET accepted_at = now()
        WHERE id = _invitation.id;
    ELSE
        _role := 'member';
    END IF;

    INSERT INTO public.user_profiles (id, email, display_name, company_id, role)
    VALUES (
        NEW.id,
        NEW.email,
        COALESCE(NEW.raw_user_meta_data->>'display_name', split_part(NEW.email, '@', 1)),
        _company_id,
        _role
    );

    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_new_user();

-- ============================================================
-- Updated_at auto-update trigger
-- ============================================================

CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER companies_updated_at
    BEFORE UPDATE ON public.companies
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER user_profiles_updated_at
    BEFORE UPDATE ON public.user_profiles
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
