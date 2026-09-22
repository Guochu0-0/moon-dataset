"""数据根解析：优先级、路径规范化、配置文件发现。"""

from pathlib import Path

import pytest

from moondata.config import DataRootSource, load_config


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """一个带 .git 标记的假仓库，配置文件发现与快照定位都以它为锚点。"""
    (tmp_path / ".git").mkdir()
    return tmp_path


def write_config(repo: Path, root: str) -> Path:
    path = repo / "moondata.toml"
    path.write_text(f'[data]\nroot = "{root}"\n', encoding="utf-8")
    return path


class TestPriority:
    def test_cli_wins_over_env_and_file(self, repo: Path, tmp_path: Path) -> None:
        write_config(repo, "F:/from-file")
        config = load_config(
            cli_data_root="H:/from-cli",
            env={"MOONDATA_DATA_ROOT": "G:/from-env"},
            start=repo,
        )
        assert config.data_root == Path("H:/from-cli")
        assert config.data_root_source is DataRootSource.CLI

    def test_env_wins_over_file(self, repo: Path) -> None:
        write_config(repo, "F:/from-file")
        config = load_config(env={"MOONDATA_DATA_ROOT": "G:/from-env"}, start=repo)
        assert config.data_root == Path("G:/from-env")
        assert config.data_root_source is DataRootSource.ENV

    def test_file_used_when_nothing_overrides(self, repo: Path) -> None:
        config_path = write_config(repo, "F:/from-file")
        config = load_config(env={}, start=repo)
        assert config.data_root == Path("F:/from-file")
        assert config.data_root_source is DataRootSource.CONFIG_FILE
        assert config.data_root_origin == str(config_path)

    def test_unset_when_no_layer_supplies_one(self, repo: Path) -> None:
        config = load_config(env={}, start=repo)
        assert config.data_root is None
        assert config.data_root_source is DataRootSource.UNSET

    def test_empty_env_var_is_ignored(self, repo: Path) -> None:
        write_config(repo, "F:/from-file")
        config = load_config(env={"MOONDATA_DATA_ROOT": "   "}, start=repo)
        assert config.data_root == Path("F:/from-file")
        assert config.data_root_source is DataRootSource.CONFIG_FILE


class TestPathNormalisation:
    def test_config_file_relative_path_resolves_against_the_config_file(
        self, repo: Path
    ) -> None:
        write_config(repo, "./imagery")
        config = load_config(env={}, start=repo)
        assert config.data_root == repo / "imagery"

    def test_tilde_is_expanded(self, repo: Path) -> None:
        config = load_config(env={"MOONDATA_DATA_ROOT": "~/moon"}, start=repo)
        assert config.data_root == Path.home() / "moon"


class TestDiscovery:
    def test_config_file_is_found_from_a_nested_directory(self, repo: Path) -> None:
        write_config(repo, "F:/from-file")
        nested = repo / "src" / "moondata"
        nested.mkdir(parents=True)
        config = load_config(env={}, start=nested)
        assert config.data_root == Path("F:/from-file")

    def test_search_stops_at_the_repo_root_marker(self, repo: Path) -> None:
        """仓库外的同名文件不应被捡起来——否则换个工作目录行为就变了。"""
        (repo.parent / "moondata.toml").write_text(
            '[data]\nroot = "F:/outside"\n', encoding="utf-8"
        )
        config = load_config(env={}, start=repo)
        assert config.data_root is None

    def test_snapshot_path_defaults_under_the_repo_root(self, repo: Path) -> None:
        config = load_config(env={}, start=repo)
        assert config.snapshot_path == repo / "data" / "stats" / "snapshot.json"

    def test_malformed_config_file_names_itself(self, repo: Path) -> None:
        path = repo / "moondata.toml"
        path.write_text("[data\n", encoding="utf-8")
        with pytest.raises(Exception) as excinfo:
            load_config(env={}, start=repo)
        assert str(path) in str(excinfo.value)
