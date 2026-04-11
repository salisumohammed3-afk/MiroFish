# MiroFish Multi-Tenant Auth Setup

## Overview

MiroFish now supports multi-company authentication with:
- **Company isolation** — each company (RWS, Dixon, QVC, etc.) only sees their own projects, simulations, and reports
- **Role-based access** — super_admin, admin, member, viewer
- **Invitation system** — send email invites that auto-assign users to a company
- **Admin dashboard** — master control at `/admin` for the super_admin

## Current Setup (Already Done)

- **Supabase project**: `LangSync Forecast` (`wyaqsyxkefjtitrxouxn`) — eu-west-2
- **Database schema**: All 5 tables deployed with RLS policies
- **Super admin**: salisumohammed3@gmail.com (password: `LangSync2026!`)
- **Companies created**: RWS, Dixon, QVC
- **Credentials**: Configured in `.env`

## Sending Invitations

1. Start MiroFish and log in at `/login`
2. Go to `/admin` → **Invitations** tab
3. Enter the person's email, select their company (RWS/Dixon/QVC), pick a role
4. Click **Send** → **Copy link** → send to the person
5. They open the link → register → auto-assigned to their company

## Redeploying on a New Machine

If setting up from scratch on a new environment:

### Step 1: Configure Environment

```bash
# .env file needs these 5 vars (already in .env.example)
SUPABASE_URL=https://wyaqsyxkefjtitrxouxn.supabase.co
SUPABASE_ANON_KEY=<anon key>
SUPABASE_SERVICE_ROLE_KEY=<service_role key>
VITE_SUPABASE_URL=https://wyaqsyxkefjtitrxouxn.supabase.co
VITE_SUPABASE_ANON_KEY=<anon key>
```

### Step 2: Install Dependencies

```bash
cd backend && pip install supabase   # or: uv sync
cd frontend && npm install           # @supabase/supabase-js already in package.json
```

### Step 3: Run

```bash
npm run dev
```

## How It Works

### Authentication Flow
```
User → Login page → Supabase Auth (email/password)
                         ↓
                   JWT access token
                         ↓
          Frontend attaches token to all API calls
                         ↓
          Backend validates JWT, looks up user profile
                         ↓
          Routes return only company-scoped data
```

### Data Isolation
- Every project and simulation is linked to a company via `project_ownership` and `simulation_ownership` tables in Supabase
- When a user creates a project/simulation, ownership is automatically registered
- List endpoints filter results by the user's `company_id`
- The super_admin bypasses all filters and sees everything

### Roles
| Role | Can do |
|------|--------|
| `super_admin` | Everything — manage companies, users, invitations, see all data |
| `admin` | Manage invitations for their company, full access to company data |
| `member` | Create and run simulations within their company |
| `viewer` | Read-only access to their company's data |

### Key Files
```
backend/
  supabase/migrations/001_initial_schema.sql  — Database schema
  app/config.py                                — Supabase env config
  app/middleware/auth.py                        — JWT validation decorators
  app/services/supabase_client.py              — Supabase client singleton
  app/services/ownership.py                     — Project/simulation ownership
  app/api/auth.py                              — Auth & admin API routes

frontend/
  src/lib/supabase.js                          — Supabase client
  src/store/auth.js                            — Auth state management
  src/api/auth.js                              — Auth API client
  src/views/LoginView.vue                      — Login page
  src/views/RegisterView.vue                   — Invitation-based registration
  src/views/AdminView.vue                      — Admin dashboard
  src/router/index.js                          — Route guards
```
