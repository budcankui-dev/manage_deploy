from services.macro_resolver import apply_macros_to_env, merge_macro_values, substitute_macros


def test_merge_macro_values_instance_overrides_default():
    defs = [{"name": "DB_URL", "default": "postgres://default"}, {"name": "MINIO_ENDPOINT", "default": "http://minio:9000"}]
    values = {"DB_URL": "postgres://prod:5432/tasks"}

    merged = merge_macro_values(defs, values)

    assert merged["DB_URL"] == "postgres://prod:5432/tasks"
    assert merged["MINIO_ENDPOINT"] == "http://minio:9000"


def test_substitute_macros_supports_dollar_and_brace_syntax():
    ctx = {"DB_URL": "postgres://x", "PEER_SOURCE_URL_API": "http://[2001:db8:1::a]:9000"}

    assert substitute_macros("connect ${DB_URL}", ctx) == "connect postgres://x"
    assert substitute_macros("upstream={{PEER_SOURCE_URL_API}}", ctx) == "upstream=http://[2001:db8:1::a]:9000"


def test_apply_macros_to_env():
    env = {"TASK_DB": "${DB_URL}", "STATIC": "ok"}
    out = apply_macros_to_env(env, {"DB_URL": "postgres://db"})

    assert out["TASK_DB"] == "postgres://db"
    assert out["STATIC"] == "ok"
