"""命令行：自检命令的退出码，以及需要影像的命令在盘不在时的降级行为。"""

from pathlib import Path

import pytest

from moondata.cli import main

PIPELINE_COMMANDS = ["overlap", "tiepoints", "transform", "patches"]


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MOONDATA_DATA_ROOT", raising=False)
    return tmp_path


@pytest.fixture
def imagery(tmp_path: Path) -> Path:
    root = tmp_path / "drive"
    root.mkdir()
    (root / "opt.tif").write_text("xx", encoding="utf-8")
    return root


class TestDoctorCommand:
    def test_exits_zero_when_the_drive_is_attached(
        self, repo: Path, imagery: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["doctor", "--data-root", str(imagery)]) == 0
        assert str(imagery) in capsys.readouterr().out

    def test_exits_one_with_a_report_not_a_traceback_when_detached(
        self, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        absent = tmp_path / "absent-drive"
        assert main(["doctor", "--data-root", str(absent)]) == 1
        captured = capsys.readouterr()
        assert "不可达" in captured.out
        assert "Traceback" not in captured.err

    def test_exits_one_when_the_root_is_unset(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["doctor"]) == 1
        assert "Traceback" not in capsys.readouterr().err


class TestPipelineCommandsNeedImagery:
    @pytest.mark.parametrize("command", PIPELINE_COMMANDS)
    def test_refuse_cleanly_when_the_drive_is_detached(
        self,
        command: str,
        repo: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        absent = tmp_path / "absent-drive"
        assert main([command, "--data-root", str(absent)]) == 1
        captured = capsys.readouterr()
        assert str(absent) in captured.err
        assert "Traceback" not in captured.err

    @pytest.mark.parametrize("command", PIPELINE_COMMANDS)
    def test_are_registered_as_subcommands(self, command: str) -> None:
        from moondata.cli import build_parser

        parser = build_parser()
        assert command in parser.format_help()


class TestPipelineCommandsDoNotWalkTheDrive:
    """「进门检查」只该 stat 一下数据根，不该为此遍历 955 GB。"""

    def test_reachability_check_does_not_fingerprint(
        self,
        repo: Path,
        imagery: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        import moondata.doctor as doctor
        from moondata.config import load_config

        # 有快照在，run_doctor 才会去算指纹——没有快照的话这个测试形同虚设。
        snapshot_path = load_config(env={}, start=repo).snapshot_path
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(
            '{"generated_at": "now", "fingerprint":'
            ' {"digest": "sha256:x", "file_count": 1, "total_bytes": 2}}',
            encoding="utf-8",
        )

        def explode(_root: Path) -> None:
            raise AssertionError("进门检查不该计算指纹")

        monkeypatch.setattr(doctor, "compute_fingerprint", explode)
        assert main(["patches", "--data-root", str(imagery)]) == 1
        assert "尚未实现" in capsys.readouterr().err
