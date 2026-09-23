"""命令行：自检命令的退出码，以及需要影像的命令在盘不在时的降级行为。"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from moondata.cli import main

REPO = Path(__file__).resolve().parents[1]
PIPELINE_COMMANDS = [
    "overlap", "tiepoints", "transform", "windows", "verify-windows", "patches", "verify-patches",
]
IMAGERY_COMMANDS = [["overlap", "35"], ["windows", "35"], ["patches", "35"], ["verify-patches"]]


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
    @pytest.mark.parametrize("command", IMAGERY_COMMANDS)
    def test_refuse_cleanly_when_the_drive_is_detached(
        self,
        command: list[str],
        repo: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        absent = tmp_path / "absent-drive"
        assert main([*command, "--data-root", str(absent)]) == 1
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
        assert main(["patches", "35", "--data-root", str(imagery)]) == 1
        assert "Traceback" not in capsys.readouterr().err


class TestOverlapCommand:
    def test_an_roi_without_raw_inputs_is_a_one_line_error(
        self, repo: Path, imagery: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["overlap", "35", "--data-root", str(imagery), "--plan-only"]) == 1
        captured = capsys.readouterr()
        assert "CE-2 分幅" in captured.err
        assert "Traceback" not in captured.err

    def test_importing_the_cli_does_not_load_the_geo_libraries(self) -> None:
        """文档档环境没有 GDAL——`import moondata.cli` 若顺带加载了它，那里就什么命令都跑不了。"""
        probe = "import sys, moondata.cli; print('osgeo' in sys.modules or 'pyproj' in sys.modules)"
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            cwd=REPO,
            env={**os.environ, "PYTHONPATH": str(REPO / "src")},
            check=True,
        )
        assert result.stdout.strip() == "False"


class TestRepoOnlySteps:
    """第二、三步只读仓库里的对齐控制点：盘不在、没装 GDAL 也照样跑。"""

    @pytest.fixture
    def in_repo(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.chdir(REPO)
        monkeypatch.setenv("MOONDATA_DATA_ROOT", str(tmp_path / "absent-drive"))

    def test_tiepoints_lists_the_generation_in_use(
        self, in_repo: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["tiepoints", "ROI_73"]) == 0
        assert "ROI_73/cropped_2/opt_tie.pts" in capsys.readouterr().out

    def test_transform_agrees_with_the_manifest(
        self, in_repo: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["transform", "35", "ROI_006", "--verify"]) == 0
        out = capsys.readouterr().out
        assert out.count("与窗口清单一致") == 2

    def test_a_disagreement_names_the_windows_and_exits_one(
        self, in_repo: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["transform", "73", "--verify"]) == 1
        out = capsys.readouterr().out
        assert "不一致" in out and "patch_0" in out
