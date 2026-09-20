export const PRODUCT_NAME = "脑壳工作台";
export const PRODUCT_SUBTITLE = "组织专属的私有智能助手";

export const copy = {
  app: { title: "脑壳工作台", description: "严格遵循企业蓝图，一步步生成结构完整、可交付的专业方案" },
  navigation: { users: "用户管理", roles: "角色管理", files: "文件管理", myFiles: "我的文件", agent: "智能助手", agentAudit: "对话审计", knowledge: "知识库管理", logout: "退出登录" },
  common: {
    create: "新建", edit: "编辑", delete: "删除", save: "保存", cancel: "取消",
    confirm: "确认", search: "查询", reset: "重置", loading: "加载中...",
    retry: "重新加载", noData: "暂无数据", requestFailed: "请求失败，请稍后重试。",
  },
  auth: {
    signIn: "登录", signingIn: "正在登录...", welcome: "欢迎登录",
    username: "用户名", password: "密码",
    usernameRequired: "用户名不能为空", passwordRequired: "密码不能为空",
    invalidCredentials: "用户名或密码错误", usernamePlaceholder: "请输入用户名",
    passwordPlaceholder: "请输入密码",
  },
  user: {
    username: "用户名", displayName: "姓名", email: "邮箱", phone: "手机号",
    status: "状态", roles: "角色", resetPassword: "重置密码", create: "新建用户",
    edit: "编辑用户", deleteConfirm: "确认删除该用户吗？",
  },
  role: {
    code: "角色编码", name: "角色名称", description: "角色说明",
    permissionAssignment: "权限分配", create: "新建角色", edit: "编辑角色",
    systemRoleNotice: "系统角色自动拥有全部启用权限。",
  },
  status: { active: "启用", disabled: "停用" },
} as const;
