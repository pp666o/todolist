import axios from 'axios';

// 修改1：使用相对路径 - 这样会通过 Vite 的代理配置
const API_URL = '/api'; // 配合 vite.config.js 中的代理设置

// 修改2：如果希望在开发/生产环境灵活切换，可以使用：
// const API_URL = import.meta.env.PROD ? '/api' : '/api';

const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const matchingService = {
  // 获取用户的潜在匹配
  getPotentialMatches(userId, topK = 10, minSimilarity = 0.3, minComplementarity = 0.3, genderFilter = null) {
    let url = `/matching/potential-matches/${userId}?top_k=${topK}&min_similarity=${minSimilarity}&min_complementarity=${minComplementarity}`;
    if (genderFilter) {
      url += `&gender_filter=${genderFilter}`;
    }
    return api.get(url);
  },
  
  // 获取用户相似度
  getUserSimilarity(userId1, userId2) {
    return api.get(`/matching/user-similarity/${userId1}/${userId2}`);
  },
  
  // 获取用户互补性
  getUserComplementarity(userId1, userId2) {
    return api.get(`/matching/user-complementarity/${userId1}/${userId2}`);
  },
  
  // 获取共同兴趣
  getCommonInterests(userId1, userId2) {
    return api.get(`/matching/common-interests/${userId1}/${userId2}`);
  },
  
  // 为一对用户推荐物品/活动
  getRecommendationsForPair(userId1, userId2, itemType = null, topK = 10) {
    let url = `/matching/recommend-for-pair/${userId1}/${userId2}?top_k=${topK}`;
    if (itemType) {
      url += `&item_type=${itemType}`;
    }
    return api.get(url);
  },
  
  // 获取关系兼容性
  getRelationshipCompatibility(userId1, userId2) {
    return api.get(`/matching/relationship-compatibility/${userId1}/${userId2}`);
  },
  
  // 获取匹配仪表板数据
  getMatchDashboard(userId1, userId2) {
    return api.get(`/matching/match-dashboard/${userId1}/${userId2}`);
  },
  
  // 添加用户资料
  addUsers(users) {
    return api.post('/matching/users', { users });
  },
  
  // 添加物品资料
  addItems(items) {
    return api.post('/matching/items', { items });
  },
  
  // 添加用户-物品交互
  addInteraction(interaction) {
    return api.post('/matching/interactions', interaction);
  }
};

export default api; 