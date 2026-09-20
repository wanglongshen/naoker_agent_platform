export const TOKENS_PER_POINT = 10000; // 1 积点 = 10000 token（与后端 points_tokens_per_point 对齐）
export const INITIAL_GRANT_POINTS = 1000; // 新用户赠送积点（与后端 points_initial_grant 对齐）
export const PLANS = [
  { name: "体验版", points: 10000, price: "¥29", desc: "适合个人试用", badge: "推荐" },
  { name: "标准版", points: 50000, price: "¥99", desc: "适合小型团队" },
  { name: "专业版", points: 200000, price: "¥299", desc: "适合深度使用" },
];
