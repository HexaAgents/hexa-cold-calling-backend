import json

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    # Direct Postgres URI (Supabase → Project Settings → Database) for DDL scripts only.
    database_url: str = ""
    openai_api_key: str = ""
    exa_api_key: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""
    twilio_twiml_app_sid: str = ""
    twilio_api_key_sid: str = ""
    twilio_api_key_secret: str = ""
    twilio_phone_numbers_json: str = "{}"
    openai_model: str = "gpt-4o-mini"
    apollo_api_key: str = ""
    backend_public_url: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    frontend_url: str = "http://localhost:8080"
    allowed_origins: str = "http://localhost:8080,http://localhost:3000"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def twilio_phone_numbers(self) -> dict[str, str]:
        """Country code -> Twilio phone number mapping. Falls back to default number for US."""
        try:
            numbers = json.loads(self.twilio_phone_numbers_json)
        except (json.JSONDecodeError, TypeError):
            numbers = {}
        if "US" not in numbers and self.twilio_phone_number:
            numbers["US"] = self.twilio_phone_number
        return numbers

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()  # type: ignore[call-arg]
