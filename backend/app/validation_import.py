"""Administrator-only import of fixed-suite runner output; not exposed as a web mutation."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re

from sqlalchemy import select, text

from .models import ValidationResult, WatchProject


def validate_result(data):
    if not isinstance(data, dict) or set(data) != {'version', 'suite', 'status', 'metrics', 'evidence'}:
        raise ValueError('测试结果字段不完整或包含未知字段')
    if not isinstance(data['version'], str) or not re.fullmatch(r'\d+\.\d+\.\d+', data['version']):
        raise ValueError('只接受明确的 Scrapy 稳定版本号')
    if data['suite'] != 'scrapy-pagination-v1' or data['status'] not in ('passed', 'failed'):
        raise ValueError('未知任务集或执行状态')
    metrics, evidence = data['metrics'], data['evidence']
    if not isinstance(metrics, dict) or not isinstance(evidence, dict) or not evidence:
        raise ValueError('缺少测试指标或运行证据')
    if (evidence.get('observed_version') != data['version']
            or not re.fullmatch(r'[a-f0-9]{64}', str(evidence.get('fixture_sha256', '')))):
        raise ValueError('缺少匹配版本或任务指纹证据')
    if data['status'] == 'passed' and evidence.get('finish_reason') != 'finished':
        raise ValueError('测试进程未正常完成')
    for key in ('expected_records', 'actual_records', 'correct_records', 'duplicates', 'retry_requests'):
        if type(metrics.get(key)) is not int or metrics[key] < 0:
            raise ValueError(f'无效指标：{key}')
    if metrics['expected_records'] == 0:
        raise ValueError('任务不能没有预期记录')
    duration = metrics.get('duration_seconds')
    if type(duration) not in (float, int) or not math.isfinite(duration) or duration < 0:
        raise ValueError('无效运行耗时')
    counts_pass = (metrics['expected_records'] == metrics['actual_records'] == metrics['correct_records']
                   and metrics['duplicates'] == 0 and metrics['retry_requests'] >= 1)
    if data['status'] == 'passed' and not counts_pass:
        raise ValueError('通过状态与采集指标不一致')
    return data


def import_result(sessions, data):
    data = validate_result(data)
    digest = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    with sessions.begin() as session:
        session.execute(text('SELECT pg_advisory_xact_lock(719436524)'))
        project = session.scalar(select(WatchProject).where(WatchProject.full_name == 'scrapy/scrapy'))
        if project is None:
            raise ValueError('请先添加 scrapy/scrapy 观察项目')
        existing = session.scalar(select(ValidationResult).where(ValidationResult.project_id == project.id, ValidationResult.digest == digest))
        if existing:
            return existing.id
        row = ValidationResult(project_id=project.id, digest=digest, **data)
        session.add(row)
        session.flush()
        return row.id


def compare_results(items):
    versions = {}
    for item in items:
        if item['suite'] == 'scrapy-pagination-v1':
            versions.setdefault(item['version'], item)
    ordered = sorted(versions, key=lambda version: tuple(map(int, version.split('.'))))
    if len(ordered) < 2:
        return None
    baseline, candidate = (versions[version] for version in ordered[-2:])
    if (baseline['metrics']['expected_records'] != candidate['metrics']['expected_records']
            or baseline['evidence'].get('fixture_sha256') != candidate['evidence'].get('fixture_sha256')):
        return None
    regression = baseline['status'] == 'passed' and candidate['status'] == 'failed'
    if regression:
        summary = '新版本在同一固定任务中未通过，建议查看失败证据后再升级。'
    elif baseline['status'] == candidate['status'] == 'passed':
        summary = '两个版本均通过分页、去重和失败重试固定任务；不代表其他场景无退化。'
    else:
        summary = '至少一个版本未通过，请查看具体指标；不能据此判断整体项目质量。'
    return dict(baseline_version=baseline['version'], candidate_version=candidate['version'], regression=regression, summary=summary)


if __name__ == '__main__':
    from .config import Settings
    from .database import database
    parser = argparse.ArgumentParser(description='导入 Scrapy 隔离测试结果，不执行测试代码')
    parser.add_argument('files', nargs='+')
    args = parser.parse_args()
    engine, sessions = database(Settings.from_env())
    try:
        for filename in args.files:
            path = Path(filename)
            if path.stat().st_size > 5_000_000:
                raise ValueError('测试结果超过 5 MB')
            result_id = import_result(sessions, json.loads(path.read_text(encoding='utf-8')))
            print(json.dumps(dict(id=result_id, status='imported')))
    finally:
        engine.dispose()
