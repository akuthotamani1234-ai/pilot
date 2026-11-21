"""The tester's own tests must not depend on your .env (no AI calls, no visible browser, no slow motion,
no real test account). These values are set before backend.config reads .env, so they win."""
import os

os.environ.update({
    "LLM_PROVIDER": "none", "LLM_MODEL": "", "HEADLESS": "true", "SLOW_MO_MS": "0", "MAX_PAGES": "0", "MAX_DEPTH": "0",
    "AUTO_REGISTER": "false", "TEST_USERNAME": "", "TEST_PASSWORD": "", "TEST_WORKERS": "1", "ALLOWED_HOSTS": "",
    "EXCLUDE_PATHS": "", "LOGIN_URL": "", "LOGIN_USER_SELECTOR": "", "LOGIN_PASSWORD_SELECTOR": "",
    "LOGIN_SUBMIT_SELECTOR": "", "LOGIN_SUCCESS_TEXT": "", "LOGIN_SUCCESS_URL": "", "QA_REQUIREMENTS": "",
    "CRAWL_SCOPE": "auto", "MAX_HEAL_ROUNDS": "2", "VISION": "auto", "VISION_MAX_FAILURES": "60",
    # live screens are for watching a run; they change worker timing that crawl tests count on (test_live_swarm.py)
    "QA_LIVE_FRAMES": "false",
    # crawl tests count requests in a fixed order; the parallel control learners have their own tests
    "EXPLORE_WORKERS": "0",
})
