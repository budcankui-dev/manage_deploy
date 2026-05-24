from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "mysql+aiomysql://root:Bupt%401234@10.112.249.191:3306/task_manager"
    # For SQLite during development:
    # database_url: str = "sqlite+aiosqlite:///./task_manager.db"

    agent_request_timeout: int = 30
    health_check_interval: int = 5
    health_check_timeout: int = 30
    health_check_max_retries: int = 3

    # Business network (container-to-container communication) - dual-stack IPv6 + IPv4
    ipv6_network: str = "2001:db8:1::/64"
    ipv4_network: str = "10.0.1.0/24"

    # Management network (Task Manager -> Node Agent) - IPv4 only
    # Agent URL is constructed as: http://{management_ip}:{agent_port}

    apscheduler_timezone: str = "Asia/Shanghai"
    service_api_token: str = "change-me-service-token"
    auth_secret: str = "change-me-auth-secret"
    access_token_expire_hours: int = 24
    auth_bypass: bool = False
    auth_bypass_role: str = "admin"
    auth_bypass_username: str = "dev"

    prefer_business_ipv6: bool = True

    minio_endpoint: str = "http://localhost:9000"
    minio_bucket: str = "task-results"


settings = Settings()
