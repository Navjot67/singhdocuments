# Deploy to Render (singhdocuments.com)

## 1) Push code to GitHub

1. Create a GitHub repo (example: `singhdocuments`)
2. Push this project to GitHub

```bash
git init
git add .
git commit -m "Initial deploy"
git branch -M main
git remote add origin https://github.com/YOUR_USER/singhdocuments.git
git push -u origin main
```

## 2) Create Render Web Service

1. Go to [https://dashboard.render.com](https://dashboard.render.com)
2. Click **New +** → **Blueprint** (or **Web Service**)
3. Connect your GitHub repo
4. Render reads `render.yaml` automatically

If creating manually:

- **Runtime:** Python 3
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `gunicorn --bind 0.0.0.0:$PORT server:app`

## 3) Set environment variables (Render → Environment)

| Key | Value |
|---|---|
| `STRIPE_SECRET_KEY` | `sk_live_...` (or `sk_test_...` for testing) |
| `STRIPE_PUBLISHABLE_KEY` | `pk_live_...` (or `pk_test_...`) |
| `STRIPE_PRICE_CENTS` | `399` or `3.99` (means $3.99 — no commas) |
| `BASE_URL` | `https://singhdocuments.com` |
| `RESEND_API_KEY` | API key from [resend.com](https://resend.com) |
| `EMAIL_FROM` | `Singh Documents <noreply@singhdocuments.com>` (after domain verify) |

Important: `BASE_URL` must match your live domain exactly (https, no trailing slash).

## 4) Deploy

Click **Deploy**.  
Your app will be live at a Render URL like:

- `https://singhdocuments.onrender.com`

Test payment there first.

## 5) Connect Hostinger domain

In **Render → your service → Settings → Custom Domains**:

1. Add `singhdocuments.com`
2. Add `www.singhdocuments.com`

In **Hostinger DNS** for `singhdocuments.com`:

### For `www` (recommended first)

- Type: `CNAME`
- Name: `www`
- Target: value shown by Render (example: `singhdocuments.onrender.com`)

### For root `@`

Use the exact record Render shows (often `A` records or `ANAME/ALIAS` if Hostinger supports it).

After DNS propagates, Render will issue free SSL automatically.

## 6) Stripe live settings

In Stripe Dashboard (Live mode):

- Use live API keys in Render env vars
- Checkout success/cancel URLs are generated from `BASE_URL`
- Test card only works in test mode

## 7) Verify production flow

1. Open `https://singhdocuments.com`
2. Fill all fields
3. Click **Pay & Download**
4. Complete Stripe payment
5. Confirm redirect back, PDF download, and email delivery

## Email setup (Resend — required on Render)

Render blocks Gmail/SMTP ports (`Network is unreachable`). Use **Resend** instead:

1. Create account at [https://resend.com](https://resend.com)
2. Create API key → copy `re_...`
3. Add domain `singhdocuments.com` in Resend and add DNS records (Hostinger DNS)
4. In Render Environment:

```env
RESEND_API_KEY=re_xxxxxxxx
EMAIL_FROM=Singh Documents <noreply@singhdocuments.com>
```

For quick testing before domain verify, use **exactly**:

```env
RESEND_API_KEY=re_xxxxxxxx
EMAIL_FROM=onboarding@resend.dev
```

Rules in Resend test mode:
- `EMAIL_FROM` must be `onboarding@resend.dev` (no custom domain yet)
- Recipient (`customer_email` in form) must be the **same email you used to sign up for Resend**

After domain `singhdocuments.com` is verified in Resend, switch to:

```env
EMAIL_FROM=Singh Documents <noreply@singhdocuments.com>
```

Then you can email any customer address.

## Troubleshooting

- **Payment works locally but not live:** check `BASE_URL` and Stripe keys (live vs test)
- **502 on Render:** open Logs tab, confirm start command uses `$PORT`
- **Preview works, pay fails:** Stripe env vars missing in Render
- **Domain not loading:** DNS not propagated yet (wait up to 24h, usually faster)
- **PDF downloads but no email:** use Resend (`RESEND_API_KEY`), not Gmail SMTP on Render. Check logs for `PDF email failed`
- **Stuck on verifying payment:** redeploy latest code (email now sends in background)
