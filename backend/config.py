from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Deployments MUST set DATABASE_URL in env (.env or process env). The default
    # below is a credentials-free local SQLite path used as a safe fallback so
    # the process can boot in dev / unit-test environments without leaking any
    # lab credentials. For production MySQL set e.g.
    #   DATABASE_URL=mysql+aiomysql://USER:PASS@HOST:PORT/task_manager
    database_url: str = "sqlite+aiosqlite:///./task_manager.db"

    agent_request_timeout: int = 60
    health_check_interval: int = 5
    health_check_timeout: int = 30
    health_check_max_retries: int = 3

    # Business network (container-to-container communication) - dual-stack IPv6 + IPv4
    ipv6_network: str = "2001:db8:1::/64"
    ipv4_network: str = "10.0.1.0/24"

    # Management network (Task Manager -> Node Agent) - IPv4 only
    # Agent URL is constructed as: http://{management_ip}:{agent_port}

    apscheduler_timezone: str = "UTC"
    service_api_token: str = "change-me-service-token"
    auth_secret: str = "change-me-auth-secret"
    access_token_expire_hours: int = 24
    auth_bypass: bool = False
    auth_bypass_role: str = "admin"
    auth_bypass_username: str = "dev"

    # 开发默认 IPv4（业务面借用管理面）；验收环境在 .env 设为 true 并配置节点 business_ipv6
    prefer_business_ipv6: bool = False

    minio_endpoint: str = "http://host.docker.internal:9000"
    minio_bucket: str = "task-results"
    minio_access_key: str = ""
    minio_secret_key: str = ""

    # Backend self-identity: how Worker containers reach this Manager process.
    # `backend_hostname` is looked up in the `nodes` table at startup; the
    # `management_ip` column there becomes the host portion of MANAGER_PUBLIC_URL.
    # `manager_public_url`, if explicitly set in env, OVERRIDES the lookup
    # (use when the backend is reachable via a different URL than what is recorded
    # in the nodes table, e.g. behind NAT or a load balancer).
    backend_hostname: str = "admin"
    backend_port: int = 8000
    manager_public_url: Optional[str] = None
    platform_scratch_root: str = "/tmp/manage_deploy"

    # SCHEDULED 模式默认运行时长（创建时未填 scheduled_end_time 则填 start+N 小时）
    default_scheduled_duration_hours: int = 2

    # Intent Parser LLM 配置
    intent_parser_engine: str = "rule"  # "llm" or "rule"
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_model: str = "qwen-plus"
    dashscope_timeout: float = 30.0
    dashscope_temperature: float = 0.1


settings = Settings()
