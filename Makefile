diff --git a/Makefile b/Makefile
index 0000000..1111111 100644
--- a/Makefile
+++ b/Makefile
@@ -1,15 +1,15 @@
 .PHONY: dev test lint type fmt
 dev:
-	\python -m uvicorn api.app:app --reload --host 0.0.0.0 --port 8000
+	OFFLINE_MODE=1 \python -m uvicorn api.app:app --reload --host 127.0.0.1 --port 8000
 
 test:
 	\pytest -q --cov=api --cov-report=term-missing --cov-report=xml --cov-fail-under=50
 
 lint:
 	\ruff check .
 	\black --check .
 
 fmt:
 	\black .
 	\ruff check --fix .
 
 type:
 	\mypy api
