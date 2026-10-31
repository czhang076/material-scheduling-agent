"""Rerun shared offline CLI evaluation without invoking a paid provider."""

from run_m3_examples import run


if __name__ == "__main__":
    from stage_guard import require_stage
    require_stage("0.4.0")
    run(prefix="M4-mock")
