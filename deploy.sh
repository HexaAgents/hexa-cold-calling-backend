#!/bin/bash
set -e

source .env

gcloud run deploy hexa-cold-calling-backend \
  --source . \
  --region us-central1 \
  --port 8000 \
  --no-allow-unauthenticated \
  --update-env-vars "^||^SUPABASE_URL=$SUPABASE_URL||SUPABASE_SERVICE_ROLE_KEY=$SUPABASE_SERVICE_ROLE_KEY||OPENAI_API_KEY=$OPENAI_API_KEY||EXA_API_KEY=$EXA_API_KEY||TWILIO_ACCOUNT_SID=$TWILIO_ACCOUNT_SID||TWILIO_AUTH_TOKEN=$TWILIO_AUTH_TOKEN||TWILIO_PHONE_NUMBER=$TWILIO_PHONE_NUMBER||TWILIO_TWIML_APP_SID=$TWILIO_TWIML_APP_SID||TWILIO_API_KEY_SID=$TWILIO_API_KEY_SID||TWILIO_API_KEY_SECRET=$TWILIO_API_KEY_SECRET||GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID||GOOGLE_CLIENT_SECRET=$GOOGLE_CLIENT_SECRET||BACKEND_PUBLIC_URL=https://hexa-cold-calling-backend-353129188949.us-central1.run.app||FRONTEND_URL=https://hexa-cold-calling-frontend.vercel.app||ALLOWED_ORIGINS=https://hexa-cold-calling-frontend.vercel.app,https://hexa-cold-calling-frontend-hexa-agents.vercel.app,https://hexa-cold-calling-frontend-git-main-hexa-agents.vercel.app"
