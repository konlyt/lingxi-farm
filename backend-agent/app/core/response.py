"""统一响应与业务异常模块。

约定所有接口返回 JSON 结构 `{code, message, data}`：
成功 code=0；失败 code 非 0（如 400 参数/业务校验失败、401 未认证、403 无权限、404 不存在）。
分页数据统一为 `{items, total, page, page_size}`。
"""
from typing import Any, Optional


def ok(data: Any = None) -> dict:
    """构造成功响应体。

    Args:
        data: 业务数据载荷，默认 None。

    Returns:
        dict: {code: 0, message: "ok", data: data} 结构。
    """
    return {"code": 0, "message": "ok", "data": data}


def fail(code: int, message: str, data: Optional[Any] = None) -> dict:
    """构造失败响应体。

    Args:
        code: 业务错误码（非 0），如 400/401/403/404。
        message: 面向用户的中文错误提示。
        data: 可选附加数据，默认 None。

    Returns:
        dict: {code, message, data} 结构。
    """
    return {"code": code, "message": message, "data": data}


def page(items: list, total: int, page_no: int, page_size: int) -> dict:
    """构造分页数据载荷。

    Args:
        items: 当前页数据列表。
        total: 满足条件的总记录数。
        page_no: 当前页码（从 1 开始）。
        page_size: 每页条数。

    Returns:
        dict: {items, total, page, page_size} 分页结构。
    """
    return {"items": items, "total": total, "page": page_no, "page_size": page_size}


class BusinessException(Exception):
    """业务异常类。

    由路由/服务层主动抛出，经全局异常处理器转换为统一响应结构；
    HTTP 状态码与业务 code 保持一致，便于前端 axios 拦截器统一处理。

    Attributes:
        code: 业务错误码。
        message: 中文错误提示。
    """

    def __init__(self, code: int = 400, message: str = "业务处理失败"):
        """初始化业务异常。

        Args:
            code: 业务错误码，默认 400。
            message: 错误提示文案，默认「业务处理失败」。
        """
        self.code = code
        self.message = message
        super().__init__(message)
