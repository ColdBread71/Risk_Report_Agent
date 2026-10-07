"""Versioned Node/field retrieval queries for the CRA/TARA workflow."""

from schemas.evidence_packet import EvidenceTargetNode
from schemas.retrieval import RetrievalField, RetrievalProfile
from prompts import load_prompt


PROFILE_VERSION = "1.7"


_TARGETED_ANCHOR_GROUPS: dict[
    tuple[EvidenceTargetNode, RetrievalField],
    tuple[tuple[str, ...], ...],
] = {
    (EvidenceTargetNode.CONTEXT, RetrievalField.COMMUNICATIONS): (
        ("源设备", "目的设备"),
        ("协议", "端口"),
        ("接口", "方向"),
        ("默认", "启用"),
    ),
    (EvidenceTargetNode.ASSETS, RetrievalField.DATA_ASSETS): (
        ("控制", "指令"),
        ("配置文件", "参数"),
        ("操作日志",),
        ("审计", "日志"),
    ),
    (EvidenceTargetNode.ASSETS, RetrievalField.CREDENTIALS_AND_KEYS): (
        ("账号", "密码"),
        ("证书", "私钥"),
        ("重置", "校验"),
        ("签名", "公钥"),
        ("令牌",),
    ),
    (EvidenceTargetNode.ASSETS, RetrievalField.SOFTWARE_AND_CONFIGURATION): (
        ("安全启动", "固件"),
        ("升级包", "公钥"),
        ("配置", "备份"),
    ),
    (EvidenceTargetNode.ASSETS, RetrievalField.HARDWARE_AND_NETWORK): (
        ("内部组件", "接口"),
        ("调试", "接口"),
        ("网络边界",),
        ("选配", "BOM"),
        ("外部设备",),
    ),
    (EvidenceTargetNode.ASSETS, RetrievalField.EXTERNAL_SERVICES): (
        ("云平台", "授权"),
        ("外部服务", "责任"),
        ("远程维护", "默认关闭"),
        ("日志", "服务器"),
        ("时间", "服务器"),
    ),
    (EvidenceTargetNode.ASSETS, RetrievalField.FUNCTION_ASSETS): (
        ("安全启动",),
        ("安全存储",),
        ("恢复出厂",),
        ("远程维护",),
        ("用户", "权限"),
    ),
    (EvidenceTargetNode.ASSETS, RetrievalField.USER_PROPERTY_ENVIRONMENT): (
        ("重伤", "死亡"),
        ("财产损失",),
        ("人员安全", "业务安全"),
        ("业务设备", "未经授权"),
    ),
}


def _profile(
    node: EvidenceTargetNode,
    field: RetrievalField,
    query: str,
    **overrides,
) -> RetrievalProfile:
    overrides.setdefault(
        "extraction_guidance",
        load_prompt("retrieval_guidance.md", "generic"),
    )
    return RetrievalProfile(node_id=node, field_id=field, query=query, **overrides)


_PROFILES = (
    _profile(
        EvidenceTargetNode.SCOPE,
        RetrievalField.PRODUCT_IDENTITY,
        "产品正式名称 型号 版本 产品组成 标准配置 供货范围 BOM 选配 选购 可选模块 软件 固件 硬件 设备标识",
    ),
    _profile(
        EvidenceTargetNode.SCOPE,
        RetrievalField.INTENDED_PURPOSE,
        "产品用途 预期用途 使用场景 主要功能 部署对象 操作说明 系统角色",
    ),
    _profile(
        EvidenceTargetNode.SCOPE,
        RetrievalField.SCOPE_BOUNDARY,
        "系统边界 产品边界 内部组件 外部系统 标准配置 供货范围 BOM 选配 选购 可选模块 交换机 接口 依赖 排除范围",
    ),
    _profile(
        EvidenceTargetNode.SCOPE,
        RetrievalField.REMOTE_SERVICES,
        "远程服务 云平台 外部平台 远程数据处理 产品功能所需 缺少服务 功能不可用 运营方 责任方 远程运维 远程升级 数据上传 外部服务依赖 降级模式",
    ),
    _profile(
        EvidenceTargetNode.SCOPE,
        RetrievalField.CLASSIFICATION_INPUTS,
        "联网能力 远程连接 关键功能 安全功能 产品类别 网络安全影响 分类依据",
    ),
    _profile(
        EvidenceTargetNode.CONTEXT,
        RetrievalField.IPRFU,
        "预期用途 合理可预见使用 误用 安装 操作 维护 退役 支持期限 安全影响",
    ),
    _profile(
        EvidenceTargetNode.CONTEXT,
        RetrievalField.USERS,
        "用户类型 管理员 运维人员 安装人员 操作员 权限 角色 责任 经验要求",
    ),
    _profile(
        EvidenceTargetNode.CONTEXT,
        RetrievalField.OPERATIONAL_ENVIRONMENT,
        "运行环境 部署环境 业务网络 物理环境 网络边界 外部系统 约束 工作条件",
    ),
    _profile(
        EvidenceTargetNode.CONTEXT,
        RetrievalField.FUNCTIONS,
        "产品功能 数据采集 控制 配置 转发 通信 监控 告警 日志 升级 维护",
        max_blocks=36,
        max_facts=24,
        extraction_guidance=load_prompt(
            "retrieval_guidance.md", "context_functions"
        ),
    ),
    _profile(
        EvidenceTargetNode.CONTEXT,
        RetrievalField.COMPONENTS,
        "产品组成 内部配置 内含 标准配置 订购信息 供货范围 BOM 硬件模块 控制器 数据采集器 通信模块 输入输出模块 交换机 路由器 网关 被动支撑部件 固件 软件 操作系统 外部设备 选配 可选",
        max_blocks=40,
        max_facts=24,
        extraction_guidance=load_prompt(
            "retrieval_guidance.md", "context_components"
        ),
    ),
    _profile(
        EvidenceTargetNode.CONTEXT,
        RetrievalField.COMMUNICATIONS,
        "通信接口 协议 端口 源设备 目的设备 连接发起 监听 服务端 客户端 业务数据方向 传输数据 默认状态 启用条件 以太网 串口 USB TCP UDP HTTP HTTPS SSH SFTP 设备协议 消息协议 时间同步 日志服务 目录服务 管理端口 调试端口 上级系统 下级设备 云平台",
        max_blocks=48,
        neighbor_window=4,
        max_facts=24,
        extraction_guidance=load_prompt(
            "retrieval_guidance.md", "context_communications"
        ),
    ),
    _profile(
        EvidenceTargetNode.CONTEXT,
        RetrievalField.SECURITY_FUNCTIONS,
        "认证 授权 访问控制 加密 证书 密钥 安全启动 安全升级 日志 审计 完整性",
        max_blocks=36,
        max_facts=24,
        extraction_guidance=load_prompt(
            "retrieval_guidance.md", "context_security_functions"
        ),
    ),
    _profile(
        EvidenceTargetNode.CONTEXT,
        RetrievalField.RDPS_DEPENDENCIES,
        "云服务 远程数据处理 外部平台 远程连接 身份认证 数据交换 降级模式 可用性",
    ),
    _profile(
        EvidenceTargetNode.ASSETS,
        RetrievalField.DATA_ASSETS,
        "存储 处理 传输 导出 删除 数据 运行数据 遥测 状态 故障告警 控制指令 操作指令 设定值 配置文件 参数 备份 日志 审计 调试 网络拓扑",
        max_blocks=40,
        neighbor_window=2,
        max_facts=24,
        extraction_guidance=load_prompt("retrieval_guidance.md", "asset_data"),
    ),
    _profile(
        EvidenceTargetNode.ASSETS,
        RetrievalField.CREDENTIALS_AND_KEYS,
        "用户 账号 密码 口令 管理员 服务账号 目录账号 凭据 序列号 设备标识 校验码 重置秘密 令牌 远程维护 访问链接 证书 私钥 协议密钥 签名公钥 验签公钥 更新公钥 导出密码 备份密码",
        max_blocks=48,
        neighbor_window=3,
        max_facts=24,
        extraction_guidance=load_prompt(
            "retrieval_guidance.md", "asset_credentials"
        ),
    ),
    _profile(
        EvidenceTargetNode.ASSETS,
        RetrievalField.SOFTWARE_AND_CONFIGURATION,
        "软件 固件 操作系统 启动镜像 安全启动 更新包 升级包 公钥 配置文件 备份 网络配置 端口配置 协议配置 业务参数 控制参数 安全策略 用户权限 证书配置 版本",
        max_blocks=44,
        neighbor_window=2,
        max_facts=24,
        extraction_guidance=load_prompt(
            "retrieval_guidance.md", "asset_software_configuration"
        ),
    ),
    _profile(
        EvidenceTargetNode.ASSETS,
        RetrievalField.HARDWARE_AND_NETWORK,
        "产品整机 硬件 内部组件 嵌入式子系统 控制器 数据采集器 通信模块 输入输出模块 物理接口 管理接口 调试接口 串口 网口 交换机 路由器 网关 内部网络 外部网络 网络边界 相邻设备 上级系统 下级设备 选配 BOM",
        max_blocks=48,
        neighbor_window=3,
        max_facts=24,
        extraction_guidance=load_prompt(
            "retrieval_guidance.md", "asset_hardware_network"
        ),
    ),
    _profile(
        EvidenceTargetNode.ASSETS,
        RetrievalField.EXTERNAL_SERVICES,
        "云平台 第三方平台 外部服务 远程数据处理 远程维护 远程升级 数据上传 时间服务 日志服务 目录服务 文件服务 上级系统 管理系统 运营方 责任方 授权 默认关闭 降级",
        max_blocks=40,
        neighbor_window=2,
        max_facts=20,
        extraction_guidance=load_prompt(
            "retrieval_guidance.md", "asset_external_services"
        ),
    ),
    _profile(
        EvidenceTargetNode.ASSETS,
        RetrievalField.FUNCTION_ASSETS,
        "数据采集 数据转发 业务控制 设备管理 配置 登录 用户管理 权限 密码 证书 密钥 安全通信 安全启动 安全存储 软件固件更新 日志 审计 时间同步 恢复出厂 远程维护",
        max_blocks=48,
        neighbor_window=2,
        max_facts=24,
        extraction_guidance=load_prompt(
            "retrieval_guidance.md", "asset_functions"
        ),
    ),
    _profile(
        EvidenceTargetNode.ASSETS,
        RetrievalField.USER_PROPERTY_ENVIRONMENT,
        "用户 运维人员 管理员 第三方人员 人身安全 生命 重伤 死亡 财产损失 业务设备 业务安全 业务运行 业务连续性 相邻设备 外部系统 基础设施服务 环境 公共利益",
        max_blocks=40,
        neighbor_window=2,
        max_facts=20,
        extraction_guidance=load_prompt(
            "retrieval_guidance.md", "asset_impacts"
        ),
    ),
)

PROFILES = {(profile.node_id, profile.field_id): profile for profile in _PROFILES}


def get_retrieval_profile(
    node_id: EvidenceTargetNode,
    field_id: RetrievalField,
) -> RetrievalProfile:
    """Return the reviewed default query for one valid Node/field pair."""
    try:
        return PROFILES[(node_id, field_id)]
    except KeyError as exc:
        raise ValueError(f"No retrieval profile for {node_id.value}/{field_id.value}") from exc


def get_profiles_for_node(node_id: EvidenceTargetNode) -> tuple[RetrievalProfile, ...]:
    """Return the reviewed fields for one node in stable extraction order."""
    profiles = tuple(profile for profile in _PROFILES if profile.node_id == node_id)
    if not profiles:
        raise ValueError(f"No retrieval profiles for {node_id.value}")
    return profiles


def get_targeted_anchor_groups(
    node_id: EvidenceTargetNode,
    field_id: RetrievalField,
) -> tuple[tuple[str, ...], ...]:
    """Return small reviewed anchor groups that must survive dense ranking."""
    return _TARGETED_ANCHOR_GROUPS.get((node_id, field_id), ())


__all__ = [
    "PROFILE_VERSION",
    "PROFILES",
    "get_profiles_for_node",
    "get_retrieval_profile",
    "get_targeted_anchor_groups",
]
