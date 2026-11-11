# Review both pins and rescan the final image before cloud deployment.
ARG LAMBDA_BASE_IMAGE=public.ecr.aws/lambda/python:3.13@sha256:3bf1fa4c9bdc5e41d704ae2480b6a26a7b0e2fa6bfb1933f621c658999a2e7da
FROM ${LAMBDA_BASE_IMAGE}
# The upstream image can lag security fixes. Use a versioned AL2023 snapshot,
# not a moving "latest" repository, and fail the build if patching fails.
RUN dnf upgrade -y --refresh --releasever=2023.12.20261109 \
      --setopt=install_weak_deps=0 \
    && dnf clean all
ARG APP_RELEASE=demo-a
ARG APP_HEALTH=healthy
COPY app.py ${LAMBDA_TASK_ROOT}/app.py
RUN python -c 'import json, os, pathlib, re; release=os.environ["APP_RELEASE"]; health=os.environ["APP_HEALTH"]; assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", release), "Invalid APP_RELEASE"; assert health in {"healthy", "failing"}, "Invalid APP_HEALTH"; pathlib.Path(os.environ["LAMBDA_TASK_ROOT"], "release.json").write_text(json.dumps({"release":release,"health":health})+"\n")'
CMD ["app.handler"]
