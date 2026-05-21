# Deploy to Hostinger (singhdocuments.com)

This app needs **Python + Flask** (not plain static hosting). On Hostinger, use a **VPS** plan.

## 1) Domain DNS (Hostinger panel)

1. Open **Domains** → `singhdocuments.com` → **DNS / Nameservers**
2. Add an **A record**:
   - Name: `@`
   - Points to: your VPS public IP
3. Add another **A record** (optional but recommended):
   - Name: `www`
   - Points to: same VPS IP

Wait 5–30 minutes for DNS to propagate.

## 2) Stripe production settings

In Stripe Dashboard:

1. Switch to **Live mode**
2. Copy live keys into server `.env`:
   - `STRIPE_SECRET_KEY=sk_live_...`
   - `STRIPE_PUBLISHABLE_KEY=pk_live_...`
3. Set:
   - `BASE_URL=https://singhdocuments.com`
   - `STRIPE_PRICE_CENTS=999` (or your price)

Checkout return URLs are built from `BASE_URL` automatically.

## 3) Upload project to VPS

SSH into VPS, then:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx
```

Upload project folder (git clone or SFTP), then:

```bash
cd /var/www/blane-lease
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt gunicorn
cp .env.example .env
nano .env
```

Set production values in `.env`:

```env
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_PRICE_CENTS=999
BASE_URL=https://singhdocuments.com
PORT=8000
```

## 4) Run app with Gunicorn (systemd)

Create service file:

```bash
sudo nano /etc/systemd/system/singhdocuments.service
```

Paste:

```ini
[Unit]
Description=Singh Documents PDF App
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/blane-lease
EnvironmentFile=/var/www/blane-lease/.env
ExecStart=/var/www/blane-lease/.venv/bin/gunicorn -w 2 -b 127.0.0.1:8000 server:app
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable singhdocuments
sudo systemctl start singhdocuments
sudo systemctl status singhdocuments
```

## 5) Nginx reverse proxy + SSL

```bash
sudo nano /etc/nginx/sites-available/singhdocuments.com
```

Paste:

```nginx
server {
    listen 80;
    server_name singhdocuments.com www.singhdocuments.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable site:

```bash
sudo ln -s /etc/nginx/sites-available/singhdocuments.com /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d singhdocuments.com -d www.singhdocuments.com
```

## 6) Test live site

1. Open `https://singhdocuments.com`
2. Fill form and preview
3. Click **Pay & Download**
4. Complete Stripe payment
5. Confirm PDF downloads after redirect

## Important notes

- Shared Hostinger web hosting (PHP-only) usually **cannot** run this Flask app.
- Use **Hostinger VPS** (or Cloud VPS).
- Keep `.env` secret; never commit it to git.
- For support email/branding, you can later add your logo and contact info in `public/index.html`.
