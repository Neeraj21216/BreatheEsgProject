# Deployment Guide

## Frontend on Vercel

1. Create a Vercel project from the `frontend/` folder.
2. Ensure Vercel installs dependencies and runs:
   - `npm install`
   - `npm run build`
3. Set environment variables in Vercel:
   - `VITE_API_BASE_URL=https://<your-render-app>.onrender.com/api`
4. Deploy the site.

The frontend will use this variable at runtime and call the backend API on Render.

## Backend on Render

This repository includes `render.yaml` and a Dockerfile for Render.

1. Create a Render Web Service using the repository.
2. Choose Docker as the runtime and keep `render.yaml` enabled.
3. Define these environment variables in Render:
   - `DJANGO_SETTINGS_MODULE=settings`
   - `DEBUG=False`
   - `ALLOWED_HOSTS=.onrender.com localhost 127.0.0.1`
   - `SECRET_KEY` (Render can generate one)
4. If you want managed production storage, add a Render PostgreSQL database and set:
   - `DATABASE_URL` to the connection string from the Render Postgres service

Render will build the Docker image and run the Django backend.

## Notes for split deployment

- The frontend is built and served statically by Vercel.
- The backend is a Django API service on Render.
- The frontend uses `VITE_API_BASE_URL` to target the Render-hosted API instead of the same origin.

## Local development

1. Backend
   - `cd BreathESG`
   - `python -m venv venv`
   - `venv\Scripts\activate` (Windows) or `source venv/bin/activate`
   - `pip install -r ../requirements.txt`
   - `python manage.py migrate`
   - `python manage.py runserver 8000`

2. Frontend
   - `cd ../frontend`
   - `npm install`
   - `npm run dev`

3. Visit `http://localhost:5173`.

The Vite dev server proxies `/api` to `http://127.0.0.1:8000`, so the frontend works against the local Django API.
