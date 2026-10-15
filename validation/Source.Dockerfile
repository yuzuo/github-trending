FROM python:3.12-slim
WORKDIR /suite
COPY source_suite.py /suite/source_suite.py
USER 65534:65534
ENV PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-I", "/suite/source_suite.py"]
