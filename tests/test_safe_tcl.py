"""safe_tcl 占位符:只有 {N} 是参数位,其余花括号原样交给 Tcl。"""

from unittest.mock import AsyncMock, patch

import pytest

from vivado_mcp.tools import tcl_tools
from vivado_mcp.vivado.tcl_utils import TclResult


async def _run(template, args=None):
    """调用 safe_tcl,返回 (工具返回值, 实际下发的 Tcl 命令或 None)。"""
    session = AsyncMock()
    session.execute.return_value = TclResult("ok", 0, is_error=False)
    with patch.object(tcl_tools, "_require_session", return_value=session):
        result = await tcl_tools.safe_tcl(template, args=args)
    sent = session.execute.await_args.args[0] if session.execute.await_count else None
    return result, sent


@pytest.mark.asyncio
@pytest.mark.parametrize(("template", "args", "expected"), [
    (
        "add_files -fileset sources_1 -norecurse {0}; "
        "set_property FILE_TYPE {Memory Initialization Files} [get_files {0}]",
        ["C:/a b/x.coe"],
        'add_files -fileset sources_1 -norecurse "C:/a b/x.coe"; '
        'set_property FILE_TYPE {Memory Initialization Files} [get_files "C:/a b/x.coe"]',
    ),
    ("add_files {*}[glob {0}/*.v]", ["C:/src"], 'add_files {*}[glob "C:/src"/*.v]'),
    ("set x {}; puts {0}", ["v"], 'set x {}; puts "v"'),
    ("puts {0} }", ["v"], 'puts "v" }'),
    # args 足够时 {1} 仍按占位符处理(与旧 str.format 行为一致)
    ("if {1} {puts {0}}", ["a", "b"], 'if "b" {puts "a"}'),
    ("create_project {0} {1} -part {2}", ["p", "C:/my dir", "xc7a35t"],
     'create_project "p" "C:/my dir" -part "xc7a35t"'),
    ("puts {1}{0}", ["a", "b"], 'puts "b""a"'),
    # 参数值里的 {1} 已被转义,不会被二次替换
    ("puts {0}", ["{1}"], r'puts "\{1\}"'),
    # 前导零与旧 str.format 一致:{01} 即 {1}
    ("puts {01}", ["a", "b"], 'puts "b"'),
    # 只认 ASCII 数字:全角数字不是占位符,原样交给 Tcl
    ("puts {１} {0}", ["a"], 'puts {１} "a"'),
])
async def test_braces_pass_through(template, args, expected):
    result, sent = await _run(template, args)
    assert sent == expected
    assert not result.startswith("[ERROR]")


@pytest.mark.asyncio
@pytest.mark.parametrize(("template", "args", "bad"), [
    ("if {1} {puts {0}}", ["a"], "{1}"),
    ("puts {0}", None, "{0}"),
    ("puts {0} {3} {3}", ["a"], "{3}"),
    # 超长数字不能让 int() 抛 ValueError(4300 位上限)
    ("puts {" + "9" * 5000 + "}", ["a"], "9" * 50),
])
async def test_out_of_range_placeholder_returns_error(template, args, bad):
    result, sent = await _run(template, args)
    assert sent is None
    assert result.startswith("[ERROR] safe_tcl 模板占位符")
    assert bad in result
    assert f"共 {len(args or [])} 个" in result
    assert "Tcl 字面量" in result
