<template>
  <div class="match-details">
    <div class="container">
      <div class="page-header">
        <h1 class="page-title">匹配详情</h1>
        <router-link to="/matches" class="btn btn-secondary">
          <i class="el-icon-back"></i> 返回匹配列表
        </router-link>
      </div>
      
      <div v-if="loading" class="loading-container">
        <el-skeleton style="width: 100%" animated>
          <template #template>
            <div style="padding: 20px;">
              <el-skeleton-item variant="image" style="width: 100%; height: 240px; margin-bottom: 20px;" />
              <el-skeleton-item variant="h1" style="width: 50%;" />
              <el-skeleton-item variant="text" style="margin-right: 16px; width: 30%;" />
              <el-skeleton-item variant="text" style="width: 100%;" />
              <el-skeleton-item variant="text" style="width: 100%;" />
            </div>
          </template>
        </el-skeleton>
      </div>
      
      <div v-else-if="error" class="error-alert">
        <el-alert :title="error" type="error" :closable="false"></el-alert>
      </div>
      
      <template v-else>
        <!-- 匹配摘要卡片 -->
        <div class="dashboard-card card section">
          <div class="users-container">
            <div class="user-profile">
              <div class="user-avatar">
                <img :src="user1Data?.avatar_url || '../assets/default-avatar.svg'" alt="用户1头像" class="avatar">
              </div>
              <div class="user-info">
                <h3>{{ user1Data?.name || `用户 ${userId1}` }}</h3>
                <p v-if="user1Data?.location">
                  <i class="el-icon-location"></i> {{ user1Data.location }}
                </p>
              </div>
            </div>
            
            <div class="compatibility-indicator">
              <div class="compatibility-score">
                <span class="score-value" :class="getScoreClass(dashboardData.match_summary?.compatibility_score || 0)">
                  {{ ((dashboardData.match_summary?.compatibility_score || 0) * 100).toFixed(0) }}%
                </span>
                <span class="score-label">匹配度</span>
              </div>
              <div class="compatibility-level">{{ dashboardData.match_summary?.compatibility_level || '未知' }}</div>
              <div class="relationship-type">{{ dashboardData.match_summary?.relationship_type || '一般关系' }}</div>
            </div>
            
            <div class="user-profile">
              <div class="user-avatar">
                <img :src="user2Data?.avatar_url || '../assets/default-avatar.svg'" alt="用户2头像" class="avatar">
              </div>
              <div class="user-info">
                <h3>{{ user2Data?.name || `用户 ${userId2}` }}</h3>
                <p v-if="user2Data?.location">
                  <i class="el-icon-location"></i> {{ user2Data.location }}
                </p>
              </div>
            </div>
          </div>
          
          <div class="compatibility-actions">
            <router-link :to="`/recommendations/${userId1}/${userId2}`" class="btn btn-primary">
              <i class="el-icon-magic-stick"></i> 为你们推荐活动
            </router-link>
          </div>
        </div>
        
        <!-- 匹配指标卡片 -->
        <div class="metrics-container">
          <div class="metric-card card section">
            <h3 class="metric-title">匹配指标</h3>
            <el-row :gutter="20">
              <el-col :span="8">
                <div class="metric-item">
                  <div class="metric-name">相似度</div>
                  <el-progress 
                    type="dashboard" 
                    :percentage="((dashboardData.detailed_metrics?.similarity || 0) * 100).toFixed(0)" 
                    :color="getProgressColor(dashboardData.detailed_metrics?.similarity || 0)"
                  ></el-progress>
                  <div class="metric-description">你们之间的相似程度</div>
                </div>
              </el-col>
              
              <el-col :span="8">
                <div class="metric-item">
                  <div class="metric-name">互补性</div>
                  <el-progress 
                    type="dashboard" 
                    :percentage="((dashboardData.detailed_metrics?.complementarity || 0) * 100).toFixed(0)" 
                    :color="getProgressColor(dashboardData.detailed_metrics?.complementarity || 0)"
                  ></el-progress>
                  <div class="metric-description">你们之间的互补程度</div>
                </div>
              </el-col>
              
              <el-col :span="8">
                <div class="metric-item">
                  <div class="metric-name">共同兴趣</div>
                  <div class="interest-count">{{ dashboardData.match_summary?.common_interests_count || 0 }}</div>
                  <div class="metric-description">你们共有的兴趣爱好数量</div>
                </div>
              </el-col>
            </el-row>
          </div>
        </div>
        
        <!-- 性格特质比较卡片 -->
        <personality-comparison
          :user-id1="userId1"
          :user-id2="userId2"
          :user1-name="user1Data?.name || `用户 ${userId1}`"
          :user2-name="user2Data?.name || `用户 ${userId2}`"
          class="card section"
        ></personality-comparison>
        
        <!-- 共同兴趣卡片 -->
        <div v-if="dashboardData.detailed_metrics?.common_interests?.length" class="common-interests card section">
          <h3 class="section-title">共同兴趣</h3>
          <div class="interests-container">
            <span v-for="(interest, idx) in dashboardData.detailed_metrics.common_interests" :key="idx" class="interest-tag tag">
              {{ interest }}
            </span>
          </div>
        </div>
        
        <!-- 推荐活动卡片 -->
        <div v-if="dashboardData.top_recommendations" class="recommendations-section">
          <h3 class="section-title">推荐内容</h3>
          <el-row :gutter="20">
            <el-col v-if="dashboardData.top_recommendations.activities?.length" :xs="24" :sm="12" :md="8">
              <div class="recommendation-card card">
                <div class="rec-icon"><i class="el-icon-date"></i></div>
                <h4>推荐活动</h4>
                <div v-for="activity in dashboardData.top_recommendations.activities" :key="activity.item_id" class="rec-item">
                  <div class="rec-name">{{ activity.name }}</div>
                  <div class="rec-score">匹配度: {{ (activity.score * 100).toFixed(0) }}%</div>
                  <div v-if="activity.description" class="rec-description">{{ activity.description }}</div>
                </div>
              </div>
            </el-col>
            
            <el-col v-if="dashboardData.top_recommendations.travel?.length" :xs="24" :sm="12" :md="8">
              <div class="recommendation-card card">
                <div class="rec-icon"><i class="el-icon-location-information"></i></div>
                <h4>推荐旅行</h4>
                <div v-for="trip in dashboardData.top_recommendations.travel" :key="trip.item_id" class="rec-item">
                  <div class="rec-name">{{ trip.name }}</div>
                  <div class="rec-score">匹配度: {{ (trip.score * 100).toFixed(0) }}%</div>
                  <div v-if="trip.description" class="rec-description">{{ trip.description }}</div>
                </div>
              </div>
            </el-col>
            
            <el-col v-if="dashboardData.top_recommendations.general?.length" :xs="24" :sm="12" :md="8">
              <div class="recommendation-card card">
                <div class="rec-icon"><i class="el-icon-goods"></i></div>
                <h4>其他推荐</h4>
                <div v-for="item in dashboardData.top_recommendations.general" :key="item.item_id" class="rec-item">
                  <div class="rec-name">{{ item.name }}</div>
                  <div class="rec-score">匹配度: {{ (item.score * 100).toFixed(0) }}%</div>
                  <div v-if="item.description" class="rec-description">{{ item.description }}</div>
                </div>
              </div>
            </el-col>
          </el-row>
          
          <div class="view-more-container">
            <router-link :to="`/recommendations/${userId1}/${userId2}`" class="btn btn-primary">
              查看更多推荐
            </router-link>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { matchingService } from '../services/api'
import PersonalityComparison from '../components/PersonalityComparison.vue'

export default {
  name: 'MatchDetails',
  components: {
    PersonalityComparison
  },
  setup() {
    const route = useRoute()
    const userId1 = computed(() => route.params.userId1)
    const userId2 = computed(() => route.params.userId2)
    
    const loading = ref(true)
    const error = ref('')
    const dashboardData = ref({})
    const user1Data = ref(null)
    const user2Data = ref(null)
    
    const fetchDashboardData = async () => {
      loading.value = true
      error.value = ''
      
      try {
        const response = await matchingService.getMatchDashboard(userId1.value, userId2.value)
        dashboardData.value = response.data
        
        // 模拟获取用户数据 (实际应该从API获取)
        user1Data.value = {
          user_id: userId1.value,
          name: `用户 ${userId1.value}`,
          avatar_url: null,
          location: '北京'
        }
        
        user2Data.value = {
          user_id: userId2.value,
          name: dashboardData.value.match_summary?.user_name || `用户 ${userId2.value}`,
          avatar_url: null,
          location: '上海'
        }
      } catch (err) {
        console.error('获取匹配详情出错:', err)
        error.value = err.response?.data?.detail || '获取匹配详情失败，请稍后再试'
      } finally {
        loading.value = false
      }
    }
    
    const getScoreClass = (score) => {
      if (score >= 0.7) return 'match-score-high'
      if (score >= 0.4) return 'match-score-medium'
      return 'match-score-low'
    }
    
    const getProgressColor = (value) => {
      if (value >= 0.7) return '#38b000'
      if (value >= 0.4) return '#ffb703'
      return '#d62828'
    }
    
    onMounted(() => {
      fetchDashboardData()
    })
    
    return {
      userId1,
      userId2,
      loading,
      error,
      dashboardData,
      user1Data,
      user2Data,
      getScoreClass,
      getProgressColor
    }
  }
}
</script>

<style scoped>
.match-details {
  padding-bottom: 3rem;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2rem;
}

.page-title {
  margin: 0;
  color: var(--primary-color);
}

.loading-container {
  margin-bottom: 2rem;
}

.error-alert {
  margin-bottom: 2rem;
}

.dashboard-card {
  margin-bottom: 2rem;
}

.users-container {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
}

.user-profile {
  display: flex;
  align-items: center;
  width: 30%;
}

.user-avatar {
  margin-right: 1rem;
}

.user-avatar .avatar {
  width: 70px;
  height: 70px;
  border: 3px solid white;
  box-shadow: 0 4px 10px rgba(0, 0, 0, 0.1);
}

.user-info h3 {
  margin: 0 0 0.5rem 0;
  font-size: 1.2rem;
}

.user-info p {
  margin: 0;
  font-size: 0.9rem;
  color: #666;
}

.compatibility-indicator {
  text-align: center;
  width: 40%;
  padding: 1rem;
  background-color: var(--grey-color);
  border-radius: 10px;
}

.compatibility-score {
  margin-bottom: 0.5rem;
}

.score-value {
  font-size: 2.5rem;
  font-weight: bold;
  display: block;
}

.score-label {
  font-size: 1rem;
  color: #666;
}

.compatibility-level {
  font-size: 1.2rem;
  font-weight: 600;
  margin-bottom: 0.5rem;
}

.relationship-type {
  font-size: 0.9rem;
  color: #666;
}

.compatibility-actions {
  text-align: center;
}

.metrics-container {
  margin-bottom: 2rem;
}

.metric-card {
  padding: 1.5rem;
}

.metric-title {
  margin-top: 0;
  margin-bottom: 1.5rem;
  font-size: 1.3rem;
  color: var(--primary-color);
}

.metric-item {
  text-align: center;
}

.metric-name {
  font-size: 1.1rem;
  font-weight: 600;
  margin-bottom: 1rem;
}

.metric-description {
  font-size: 0.9rem;
  color: #666;
  margin-top: 0.5rem;
}

.interest-count {
  font-size: 3rem;
  font-weight: bold;
  color: var(--primary-color);
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 20px 0;
}

.common-interests {
  margin-bottom: 2rem;
  padding: 1.5rem;
}

.interests-container {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.interest-tag {
  font-size: 1rem;
  background-color: var(--primary-color);
  color: white;
}

.recommendations-section {
  margin-bottom: 2rem;
}

.recommendation-card {
  height: 100%;
  padding: 1.5rem;
  margin-bottom: 1.5rem;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.rec-icon {
  font-size: 2.5rem;
  color: var(--primary-color);
  margin-bottom: 1rem;
}

.recommendation-card h4 {
  font-size: 1.2rem;
  margin-top: 0;
  margin-bottom: 1.5rem;
  text-align: center;
}

.rec-item {
  width: 100%;
  padding: 1rem;
  margin-bottom: 1rem;
  background-color: var(--grey-color);
  border-radius: 8px;
}

.rec-name {
  font-weight: 600;
  margin-bottom: 0.5rem;
}

.rec-score {
  font-size: 0.9rem;
  color: var(--primary-color);
  margin-bottom: 0.5rem;
}

.rec-description {
  font-size: 0.85rem;
  color: #555;
}

.view-more-container {
  text-align: center;
  margin-top: 1.5rem;
}

@media (max-width: 768px) {
  .users-container {
    flex-direction: column;
    gap: 1.5rem;
  }
  
  .user-profile,
  .compatibility-indicator {
    width: 100%;
  }
}
</style> 