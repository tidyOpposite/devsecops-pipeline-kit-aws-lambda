# Refresh the base digest deliberately before final cloud acceptance.
ARG LAMBDA_BASE_IMAGE=public.ecr.aws/lambda/python:3.13@sha256:d018a22af8e9927f446deb98b69ce00500b75e040cd4434d817f0a56a5b3ab01
FROM ${LAMBDA_BASE_IMAGE}
ARG APP_RELEASE=demo-a
ARG APP_HEALTH=healthy
COPY app.py ${LAMBDA_TASK_ROOT}/app.py
RUN python -c 'import json, os, pathlib, re; release=os.environ["APP_RELEASE"]; health=os.environ["APP_HEALTH"]; assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", release), "Invalid APP_RELEASE"; assert health in {"healthy", "failing"}, "Invalid APP_HEALTH"; pathlib.Path(os.environ["LAMBDA_TASK_ROOT"], "release.json").write_text(json.dumps({"release":release,"health":health})+"\n")'
CMD ["app.handler"]
