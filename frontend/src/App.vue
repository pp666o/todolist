<script setup>
import { ref, reactive, onMounted } from 'vue'
import axios from 'axios'

// FastAPI 后端地址 (根据实际情况修改)
const backendUrl = 'http://localhost:8000' // 开发时后端地址

// 响应式状态
const userId = ref('user_0001') // <-- 恢复默认值或设为空 ''
const topK = ref(10)
const adaptiveFactor = ref(0.0) // 默认中性
const includeMatches = ref(false)
const scenario = ref('') // 推荐场景，默认为空

const recommendations = ref([])
const potentialMatches = ref([]) // 存储可能的用户推荐
const isLoading = ref(false)
const error = ref(null)
const apiResponse = reactive({
    adaptive_factor_used: null,
    factor_source: null
})

// 获取推荐的方法
async function fetchRecommendations() {
    isLoading.value = true
    error.value = null
    recommendations.value = []
    potentialMatches.value = []
    apiResponse.adaptive_factor_used = null
    apiResponse.factor_source = null

    if (!userId.value) {
        error.value = '请选择一个用户 ID'
        isLoading.value = false
        return
    }

    try {
        // 构建请求 URL 和参数
        const apiUrl = `${backendUrl}/recommendations/${userId.value}`
        const params = {
            top_k: topK.value,
            include_potential_matches: includeMatches.value
        }
        // 只有当 adaptiveFactor 不是 null 或 undefined 时才添加
        if (adaptiveFactor.value !== null && adaptiveFactor.value !== undefined) {
            params.adaptive_factor = adaptiveFactor.value
        }
         // 只有当 scenario 不为空时才添加
        if (scenario.value) {
             params.scenario = scenario.value
        }

        console.log("请求 API:", apiUrl, "参数:", params); // 调试日志

        const response = await axios.get(apiUrl, { params })

        console.log("API 响应:", response.data); // 调试日志

        // 分离物品推荐和用户推荐 (如果后端混合返回)
        // 注意：当前后端实现并未在 RecommendationResponse 中明确区分用户推荐
        // 后端 get_recommendations 需要调整才能完美支持这里的分离
        // 暂时假设 recommendations 列表只包含物品
        recommendations.value = response.data.recommendations || []

        // 存储API返回的因子信息
        apiResponse.adaptive_factor_used = response.data.adaptive_factor_used
        apiResponse.factor_source = response.data.factor_source

        // --- 潜在用户匹配的处理 (需要后端配合) ---
        // 如果 includeMatches 为 true，理论上后端应该在响应中包含匹配的用户信息
        // 或者前端需要调用 /matching/potential-matches/{user_id} 端点
        // 为了演示，我们假设 response.data *可能* 包含一个 potential_matches 字段
        // 这需要后端 API (/recommendations/{user_id}) 的修改才能实现
        // if (includeMatches.value && response.data.potential_matches) {
        //     potentialMatches.value = response.data.potential_matches;
        // }
        // -------------------------------------------

    } catch (err) {
        console.error("API 请求错误:", err)
        if (err.response) {
            error.value = `错误: ${err.response.status} - ${err.response.data.detail || '无法获取推荐'}`
        } else if (err.request) {
            error.value = '无法连接到服务器，请确保后端正在运行。'
        } else {
            error.value = `请求失败: ${err.message}`
        }
    } finally {
        isLoading.value = false
    }
}

</script>

<template>
  <div id="app">
    <header class="app-header">
      <div class="container flex-between">
        <router-link to="/" class="logo">
          <h1>趣配 <span>MatchMaker</span></h1>
        </router-link>
        <nav class="main-nav">
          <router-link to="/" class="nav-item">首页</router-link>
          <router-link to="/matches" class="nav-item">匹配</router-link>
        </nav>
      </div>
    </header>

    <main class="app-content">
      <router-view></router-view>
    </main>
    
    <footer class="app-footer">
      <div class="container">
        <p>&copy; 2023 趣配 MatchMaker - 为您找到最合适的匹配</p>
      </div>
    </footer>
  </div>
</template>

<style scoped>
#app {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.app-header {
  background-color: white;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
  padding: 1rem 0;
  position: sticky;
  top: 0;
  z-index: 1000;
}

.logo {
  text-decoration: none;
}

.logo h1 {
  font-size: 1.5rem;
  color: var(--primary-color);
  margin: 0;
}

.logo span {
  color: var(--secondary-color);
  font-weight: 300;
}

.main-nav {
  display: flex;
  gap: 1.5rem;
}

.nav-item {
  text-decoration: none;
  color: var(--text-color);
  font-weight: 500;
  transition: color 0.2s ease;
  padding: 0.5rem 0;
  position: relative;
}

.nav-item::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  width: 0;
  height: 2px;
  background-color: var(--primary-color);
  transition: width 0.3s ease;
}

.nav-item:hover {
  color: var(--primary-color);
}

.nav-item:hover::after,
.router-link-active::after {
  width: 100%;
}

.router-link-active {
  color: var(--primary-color);
}

.app-content {
  flex: 1;
  padding: 2rem 0;
}

.app-footer {
  background-color: var(--grey-color);
  padding: 1.5rem 0;
  margin-top: auto;
}

.app-footer p {
  text-align: center;
  margin: 0;
  color: #666;
}

@media (max-width: 768px) {
  .app-header .container {
    flex-direction: column;
    gap: 1rem;
  }
  
  .main-nav {
    justify-content: center;
  }
}

.container {
  max-width: 900px;
  margin: 2rem auto;
  padding: 2rem;
  font-family: sans-serif;
  background-color: #f9f9f9;
  border-radius: 8px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
}

h1 {
  text-align: center;
  color: #333;
  margin-bottom: 2rem;
}

.controls {
  background-color: #fff;
  padding: 1.5rem;
  border-radius: 6px;
  margin-bottom: 2rem;
  border: 1px solid #eee;
}

.control-group {
  margin-bottom: 1.2rem;
  display: flex;
  flex-direction: column; /* 标签和控件垂直排列 */
}

.control-group label {
  display: block;
  margin-bottom: 0.5rem;
  color: #555;
  font-weight: bold;
}

.control-group input[type="text"],
.control-group input[type="number"],
.control-group select {
  width: 100%;
  padding: 0.6rem;
  border: 1px solid #ccc;
  border-radius: 4px;
  box-sizing: border-box;
}

.control-group input[type="range"] {
  width: 100%;
  margin-top: 0.2rem;
}

.checkbox-group {
    flex-direction: row; /* 复选框和标签水平排列 */
    align-items: center;
}
.checkbox-group input[type="checkbox"] {
    margin-right: 0.5rem;
}
.checkbox-group label {
    margin-bottom: 0; /* 移除标签下边距 */
    font-weight: normal; /* 普通字体 */
}

button {
  padding: 0.8rem 1.5rem;
  background-color: #007bff;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  transition: background-color 0.2s ease;
  font-size: 1rem;
  width: 100%; /* 让按钮充满容器 */
}

button:disabled {
  background-color: #ccc;
  cursor: not-allowed;
}

button:hover:not(:disabled) {
  background-color: #0056b3;
}

.reset-button {
    background-color: #6c757d;
    font-size: 0.8rem;
    padding: 0.2rem 0.5rem;
    margin-left: 1rem;
    width: auto; /* 重置按钮不需要充满 */
}
.reset-button:hover:not(:disabled) {
    background-color: #5a6268;
}

.factor-info {
    font-size: 0.85rem;
    color: #666;
    margin-left: 1rem;
    display: inline-block; /* 或者 block 看布局需要 */
    margin-top: 0.3rem;
}

.loading,
.error,
.no-results {
  text-align: center;
  margin-top: 2rem;
  padding: 1rem;
  border-radius: 4px;
}

.loading {
  color: #555;
}

.error {
  color: #dc3545;
  background-color: #f8d7da;
  border: 1px solid #f5c6cb;
}

.no-results {
    color: #6c757d;
}

.results {
  margin-top: 2rem;
}

.results h2 {
  color: #333;
  border-bottom: 2px solid #eee;
  padding-bottom: 0.5rem;
  margin-bottom: 1rem;
}

ul {
  list-style: none;
  padding: 0;
}

.recommendation-item, .match-item {
  background-color: #fff;
  border: 1px solid #eee;
  padding: 1rem;
  margin-bottom: 1rem;
  border-radius: 4px;
}

.item-id, .item-score, .item-reason {
  margin-bottom: 0.5rem;
}

.item-id {
  font-weight: bold;
  color: #007bff;
}

.item-score {
  color: #28a745;
}

.item-reason {
  font-style: italic;
  color: #666;
  font-size: 0.9rem;
}

.item-details summary {
    cursor: pointer;
    color: #0056b3;
    margin-top: 0.5rem;
    display: inline-block;
}
.item-details pre {
    background-color: #e9ecef;
    padding: 0.8rem;
    border-radius: 4px;
    margin-top: 0.5rem;
    font-size: 0.85rem;
    white-space: pre-wrap; /* 自动换行 */
    word-wrap: break-word;
}

/* 新增下拉列表样式 (可选) */
/* .control-group select:disabled {
    background-color: #e9ecef;
    cursor: not-allowed;
} */

</style> 