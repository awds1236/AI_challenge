"""모든 테스트 공통: 이 PC에 실제로 설치된 AI 엔진·모델(프로그램 폴더의 engine·models)을 쓰지 않게 한다.

엔진은 프로그램 폴더를 먼저 찾는다 (설치형 배포용). 테스트를 실행한 PC에 진짜 엔진이 있으면 가짜 엔진 대신
진짜 모델이 답해 결과가 PC마다 달라지고, 모델 파일을 쓰는 테스트가 실제 models 폴더를 건드릴 수 있다.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolated_app_dir(tmp_path_factory, monkeypatch):
    from seomu import engine
    app = tmp_path_factory.mktemp("app")
    monkeypatch.setattr(engine, "app_dir", lambda: app)
    yield
