# 本文件必须使用 source 执行：
#
#   source scripts/activate_dev.sh
#
# 直接运行 bash scripts/activate_dev.sh 只会影响子进程，
# 无法激活当前终端的虚拟环境。

if [ -n "${ZSH_VERSION:-}" ]; then
  case "${ZSH_EVAL_CONTEXT:-}" in
    *:file)
      ;;
    *)
      echo "[ERROR] 请使用：source scripts/activate_dev.sh" >&2
      return 1 2>/dev/null || exit 1
      ;;
  esac

  SCRIPT_PATH="${(%):-%N}"
elif [ -n "${BASH_VERSION:-}" ]; then
  if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "[ERROR] 请使用：source scripts/activate_dev.sh" >&2
    exit 1
  fi

  SCRIPT_PATH="${BASH_SOURCE[0]}"
else
  SCRIPT_PATH="$0"
fi

ROOT_DIR="$(
  cd "$(dirname "${SCRIPT_PATH}")/.." &&
  pwd
)"

if [ ! -x "${ROOT_DIR}/.venv/bin/python" ]; then
  echo "[ERROR] .venv 不存在，请先执行：" >&2
  echo "  bash scripts/restore_dev.sh" >&2
  return 1 2>/dev/null || exit 1
fi

# shellcheck disable=SC1091
source "${ROOT_DIR}/.venv/bin/activate"

export PYTHONPATH="${ROOT_DIR}"

cd "${ROOT_DIR}"

echo "Python environment activated:"
echo "  VIRTUAL_ENV=${VIRTUAL_ENV}"
echo "  PYTHON=$(command -v python)"
echo "  PYTHONPATH=${PYTHONPATH}"
