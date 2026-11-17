// Local default: same origin (nginx proxies /api to the api container).
// For Azure this file is replaced at deploy time with the Container App URL.
window.APP_CONFIG = { API_URL: "" };
