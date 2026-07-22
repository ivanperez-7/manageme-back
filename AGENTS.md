# PrintPOS API — Agent Guide

## First reads
- `printpos_api/settings.py` — auth, CORS, DRF config, installed apps
- `printpos_api/urls.py` — all routes
- `utils/permissions.py` — `HasValidBranch` (per-request `x-branch-id` check)
- `productos/views.py` — dashboard_view (lines 73–119)
- `.env` — all required env vars
- `build.sh` / `render.yaml` — deploy flow

## Architecture
- **Django 5.2 / DRF 3.16**, Python 3.11.3, SQLite dev / Postgres prod
- 4 apps: `productos` (catalog), `organizacion` (clients/branches/users/profiles), `movimiento` (inventory movements), `system` (config/activity log/alerts)
- Spanish throughout: models, fields, comments, error messages
- ASGI on Render: gunicorn + uvicorn worker (`render.yaml:13`)
- Build: `pip install -r requirements.txt` → `collectstatic` → `migrate`

## Required request header
**Every API request needs `x-branch-id`** set to a branch the user's profile is assigned to. Missing it = 403. Set via `HasValidPermission` in `utils/permissions.py`.

## Movement two-step flow
1. `POST /movimientos/` creates a movement with `aprobado=False` — **no inventory mutation**
2. `POST /movimientos/{id}/aprobar/` triggers approval: entries create lots+units; exits assign units + run `verificar_vida_util()`

Approval requires `admin` role. Unapproved movements are excluded from dashboard charts.

## Testing
Run: `python manage.py test`
No pytest. Only `productos/tests.py` exists (6 model tests + serializer/viewset tests). Tests use `APITestCase` + `force_login` (SessionAuth, not JWT).

## Frontend (printpos-web)
- **Location:** `../printpos-web` (sibling repo)
- **Stack:** React 19, Vite 7, TanStack Router (file-based), TanStack Form + Zod v4, shadcn/ui new-york zinc, Tailwind 4, Recharts
- **Dev server:** `npm run dev` (port 3000)
- **Env:** `VITE_API_URL=http://localhost:8000/api/v1`
- **Test:** `npm test` (vitest), `npm run build` (includes `tsc` type-check)

### Auth & API client
- Token stored in-memory (`authStore`), refresh via `POST /token/refresh/` (cookie-based)
- `x-branch-id` header from `branch` cookie in every `withAuth` axios request
- Auth guard in `_app.tsx` `beforeLoad` — checks JWT expiry, refreshes or redirects to `/login`
- Role guard: `authRoleGuard(allowedRoles)` — admin/operativo/consulta

### Route ↔ API mapping
| Page | Backend endpoint |
|---|---|
| `/catalogo` | `GET /productos/productos/`, `/categorias/`, `/marcas/`, `/equipos/`, `/proveedores/` |
| `/dashboard` | `GET /productos/dashboard/`, `/rendimiento/` |
| `/movements` | `GET /movimientos/movimientos/` |
| `/movements/:id` | `GET /movimientos/movimientos/{id}/` |
| `/movements/new` | `POST /movimientos/movimientos/` |
| `/clients`, `/suppliers` | `GET /organizacion/clientes/`, `/proveedores/` |
| `/equipos` | `GET /productos/equipos/`, `/categorias/`, `/marcas/` |
| `/reorden` | `GET /productos/reorden/` |
| `/actividades` | `GET /system/actividades/` |
| `/settings` | `GET /system/configuracion/` |
| `/alertas` | `GET /system/alertas/`, `/refrescar/` |
| `/chatbot` | `POST /api/v1/chat/` |

### Key files in printpos-web
| File | Purpose |
|---|---|
| `src/main.tsx` | App entry: QueryClient, Router, ThemeProvider |
| `src/lib/auth.ts` | Axios instance with auth interceptors, login/logout, `authGuard` |
| `src/lib/types.ts` | Zod schemas + TypeScript types matching backend models |
| `src/lib/utils.ts` | `cn()` (clsx + tailwind-merge) |
| `src/api/endpoints.ts` | All API endpoint constants |
| `src/api/` | Per-domain modules (dashboard, catalogo, movimientos, etc.) |
| `src/hooks/use-app-form.tsx` | `<Field.InputField>`, `<Field.NumberSelectField>`, `<form.SaveButton>` |
| `src/routes/_app.tsx` | Protected layout with sidebar + auth guard |
| `src/components/ui/` | shadcn/ui components |
| `src/components/movement/` | Scan input for movement detail |
| `src/stores/authStore.ts` | In-memory access token |
| `src/stores/userStore.ts` | User profile (rol, name, etc.) |

## Known gotchas
- **Factura validation** (`validar_factura_entrada`) connects via Gmail API OAuth2. Requires `credentials.json` + `token.json` in `printpos_api/`
- **Chat** (`POST /api/v1/chat/`) requires `GEMINI_API_KEY`. LangChain agent restricted to 14 tables in `TABLAS_PERMITIDAS`
- **Alerts** not auto-generated — must hit `POST /system/alertas/refrescar/` to run generators
- **No price data** — `precio_compra`/`precio_venta` removed in migration 0004
- **No type checker** configured (no mypy, pyright, or pyproject.toml)
- **`GET /movimientos/movimientos/get_oldest/`** returns a bare date (not JSON object) for datepicker range
- **`SucursalViewSet`** is public (`permission_classes = []`), list cached 2h
