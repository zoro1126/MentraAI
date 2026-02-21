from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite:///./mentra.db"
    
    # LLM (llama-server)
    LLAMA_SERVER_URL: str = "http://localhost:8080/completion"
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 512
    
    # App Settings
    PROJECT_NAME: str = "MentraAI Backend"
    
    class Config:
        case_sensitive = True
        env_file = ".env"

settings = Settings()
