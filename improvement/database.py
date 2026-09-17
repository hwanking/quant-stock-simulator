# -*- coding: utf-8 -*-
"""SQLite 저장 계층 — append-only 우선, WAL, 스키마 초기화."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

# 운영 DB는 로컬 상태 디렉터리(.portfolio)에 둔다 — data/ 는 배포 동봉용
# 산출물 디렉터리라 변동 DB를 두면 커밋 오염이 생긴다 (스펙과 다른 점, 보고됨).
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(_BASE, '.portfolio', 'improvement.db')


#: 이 프로세스에서 표를 이미 갖춘 DB 경로 (라운드 331).
_READY: set = set()


def _open(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """연결 — **처음 여는 경로면 표부터 갖춘다** (라운드 331).

    ⚠️ 배포 앱이 `sqlite3.OperationalError: no such table: prediction_cases` 로 통째로 죽었다
    (2026-09-17). `sqlite3.connect` 는 연결만 열어도 **빈 파일을 만든다** — 새로 뜬 컨테이너에서
    화면 맨 위 버전 칩이 초기화 없이 연결을 열어 '파일은 있고 표는 없는' DB 를 남겼고, 아래의
    사후 검증이 '파일이 있다'만 보고 조회하다 죽었다. 초기화를 부르는 자리(모델 성적 줄)와 안 부르는
    자리(버전 칩 · 사후 검증 · 이슈 화면)가 섞여 있었다 — 호출부마다 고치지 않고 여는 곳 한 곳에서
    갖춘다(R120e). `CREATE TABLE IF NOT EXISTS` 라 있는 행은 안 건드리고 프로세스당 한 번이다.
    못 갖추면(읽기 전용 등) 연결은 그대로 돌려준다 — 조회가 실패하면 호출부가 사유를 적는다.
    """
    key = os.path.abspath(db_path)
    if key not in _READY:
        try:
            initialize_database(db_path)
        except Exception:                                      # noqa: BLE001
            pass
    return _open(db_path)


@contextmanager
def transaction(db_path: str = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_database(db_path: str = DEFAULT_DB_PATH) -> None:
    conn = _open(db_path)
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS prediction_cases (
            case_id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            signal_date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            model_version TEXT NOT NULL,
            rulebook_version TEXT NOT NULL,
            decision TEXT NOT NULL,
            total_score REAL NOT NULL,
            confidence_score REAL NOT NULL,
            reference_price REAL NOT NULL,
            entry_price REAL,
            target_price REAL,
            stop_price REAL,
            holding_days INTEGER NOT NULL,
            market_regime TEXT NOT NULL,
            strategy_type TEXT NOT NULL,
            data_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            exit_price REAL,
            realized_return REAL,
            max_drawdown REAL,
            result_reason TEXT,
            resolved_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_cases_signal_date
            ON prediction_cases(signal_date);
        CREATE INDEX IF NOT EXISTS idx_cases_model
            ON prediction_cases(model_version);
        CREATE INDEX IF NOT EXISTS idx_cases_status
            ON prediction_cases(status);

        CREATE TABLE IF NOT EXISTS model_versions (
            model_version TEXT PRIMARY KEY,
            rulebook_version TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            parent_version TEXT,
            change_summary TEXT NOT NULL,
            training_count INTEGER NOT NULL DEFAULT 0,
            validation_count INTEGER NOT NULL DEFAULT 0,
            oos_count INTEGER NOT NULL DEFAULT 0,
            blind_count INTEGER NOT NULL DEFAULT 0,
            validation_accuracy REAL,
            oos_accuracy REAL,
            blind_accuracy REAL,
            high_confidence_accuracy REAL,
            expected_return REAL,
            profit_factor REAL,
            max_drawdown REAL,
            signal_rate REAL,
            approved_at TEXT,
            rejection_reason TEXT
        );

        CREATE TABLE IF NOT EXISTS improvement_issues (
            issue_id TEXT PRIMARY KEY,
            issue_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            category TEXT NOT NULL,
            severity TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            detail TEXT,
            status TEXT NOT NULL,
            related_model TEXT,
            related_ticker TEXT,
            resolved_at TEXT
        );

        CREATE TABLE IF NOT EXISTS release_notes (
            release_id TEXT PRIMARY KEY,
            released_at TEXT NOT NULL,
            version TEXT NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            detail TEXT,
            is_major INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS pipeline_runs (
            run_id TEXT PRIMARY KEY,
            pipeline_type TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            added_cases INTEGER NOT NULL DEFAULT 0,
            resolved_cases INTEGER NOT NULL DEFAULT 0,
            error_count INTEGER NOT NULL DEFAULT 0,
            detail TEXT
        );

        CREATE TABLE IF NOT EXISTS research_candidates (
            candidate_id TEXT PRIMARY KEY,
            registered_at TEXT NOT NULL,
            source TEXT NOT NULL,
            year TEXT,
            core_idea TEXT NOT NULL,
            target_failure TEXT,
            required_data TEXT,
            implementable INTEGER,
            leakage_risk TEXT,
            compute_cost TEXT,
            stock_applicable INTEGER,
            etf_applicable INTEGER,
            validation_result TEXT,
            adopted INTEGER,
            decision_reason TEXT
        );
        """)
        conn.commit()
        # 기존 DB 확장 — MFE(최대 이익폭) 열이 없으면 추가한다 (append-only 유지)
        try:
            conn.execute(
                "ALTER TABLE prediction_cases ADD COLUMN max_runup REAL")
            conn.commit()
        except Exception:
            pass
        _READY.add(os.path.abspath(db_path))
    finally:
        conn.close()
