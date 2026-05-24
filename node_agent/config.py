from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "extra": "ignore"}

    agent_port: int = 8001
    docker_socket: str = "unix:///var/run/docker.sock"
    agent_data_root: str = "/var/lib/manage_deploy/tasks"


settings = Settings()