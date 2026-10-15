FROM python:3.12-slim
ARG SCRAPY_VERSION
RUN pip install --no-cache-dir --index-url https://pypi.org/simple "Scrapy==${SCRAPY_VERSION}"
WORKDIR /suite
COPY suite.py ./suite.py
USER 65534:65534
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["python", "suite.py"]
