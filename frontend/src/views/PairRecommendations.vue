<template>
  <div class="pair-recommendations">
    <div class="container">
      <div class="page-header">
        <h1 class="page-title">配对推荐</h1>
        <div class="page-actions">
          <router-link :to="`/match-details/${userId1}/${userId2}`" class="btn btn-secondary">
            <i class="el-icon-back"></i> 返回匹配详情
          </router-link>
        </div>
      </div>
      
      <div v-if="loading" class="loading-container">
        <el-skeleton style="width: 100%" animated>
          <template #template>
            <div style="padding: 20px;">
              <el-skeleton-item variant="h1" style="width: 50%;" />
              <el-skeleton-item variant="text" style="margin-right: 16px; width: 30%;" />
              <div style="display: flex; gap: 20px;">
                <div style="flex: 1;">
                  <el-skeleton-item variant="image" style="width: 100%; height: 160px; margin-bottom: 20px;" />
                </div>
                <div style="flex: 1;">
                  <el-skeleton-item variant="image" style="width: 100%; height: 160px; margin-bottom: 20px;" />
                </div>
                <div style="flex: 1;">
                  <el-skeleton-item variant="image" style="width: 100%; height: 160px; margin-bottom: 20px;" />
                </div>
              </div>
            </div>
          </template>
        </el-skeleton>
      </div>
      
      <div v-else-if="error" class="error-alert">
        <el-alert :title="error" type="error" :closable="false"></el-alert>
      </div>
      
      <template v-else>
        <div class="user-pair-header card section">
          <div class="user-pair">
            <div class="user-info">
              <div class="user-avatar">
                <img src="../assets/default-avatar.svg" alt="用户1头像" class="avatar">
              </div>
              <div class="user-name">{{ userId1 }}</div>
            </div>
            
            <div class="connection-indicator">
              <div class="connection-line"></div>
              <div class="connection-icon">
                <i class="el-icon-connection"></i>
              </div>
            </div>
            
            <div class="user-info">
              <div class="user-avatar">
                <img src="../assets/default-avatar.svg" alt="用户2头像" class="avatar">
              </div>
              <div class="user-name">{{ userId2 }}</div>
            </div>
          </div>
          
          <div class="recommendation-filters">
            <el-form :inline="true" :model="filters" class="filter-form">
              <el-form-item label="物品类型">
                <el-select v-model="filters.itemType" placeholder="选择类型" @change="fetchRecommendations">
                  <el-option label="全部" value=""></el-option>
                  <el-option label="活动" value="activity"></el-option>
                  <el-option label="旅行" value="travel"></el-option>
                  <el-option label="餐厅" value="restaurant"></el-option>
                  <el-option label="电影" value="movie"></el-option>
                </el-select>
              </el-form-item>
              
              <el-form-item label="显示数量">
                <el-select v-model="filters.topK" @change="fetchRecommendations">
                  <el-option label="10" :value="10"></el-option>
                  <el-option label="20" :value="20"></el-option>
                  <el-option label="30" :value="30"></el-option>
                </el-select>
              </el-form-item>
            </el-form>
          </div>
        </div>
        
        <div class="recommendations-list">
          <h2 class="section-title">为你们推荐的内容 ({{ recommendations.length }})</h2>
          
          <el-row :gutter="20">
            <el-col v-for="item in recommendations" :key="item.item_id" :xs="24" :sm="12" :md="8" :lg="6">
              <div class="recommendation-card card">
                <div class="rec-image">
                  <img :src="item.image_url || getDefaultImage(item.type)" alt="推荐图片">
                </div>
                
                <div class="rec-content">
                  <h3 class="rec-title">{{ item.name }}</h3>
                  
                  <div class="rec-type" v-if="item.type">
                    <el-tag size="small" :type="getTagType(item.type)">{{ item.type }}</el-tag>
                  </div>
                  
                  <div class="rec-score">
                    <div class="score-label">匹配度</div>
                    <el-progress :percentage="(item.score * 100).toFixed(0)" :color="getScoreColor(item.score)"></el-progress>
                  </div>
                  
                  <div class="rec-description" v-if="item.description">
                    {{ truncateText(item.description, 100) }}
                  </div>
                  
                  <div class="rec-meta" v-if="item.details">
                    <div class="meta-item" v-if="item.details.location">
                      <i class="el-icon-location"></i> {{ item.details.location }}
                    </div>
                    <div class="meta-item" v-if="item.details.duration">
                      <i class="el-icon-time"></i> {{ item.details.duration }}
                    </div>
                    <div class="meta-item" v-if="item.details.price">
                      <i class="el-icon-money"></i> {{ formatPrice(item.details.price) }}
                    </div>
                  </div>
                  
                  <div class="rec-tags" v-if="item.tags && item.tags.length">
                    <span v-for="(tag, idx) in item.tags.slice(0, 3)" :key="idx" class="tag">
                      {{ tag }}
                    </span>
                    <span v-if="item.tags.length > 3" class="more-count">+{{ item.tags.length - 3 }}</span>
                  </div>
                  
                  <div class="rec-actions">
                    <el-button type="primary" size="small" @click="recordInteraction(item.item_id, 'like')">
                      <i class="el-icon-star-off"></i> 收藏
                    </el-button>
                    <el-button type="success" size="small" @click="recordInteraction(item.item_id, 'select')">
                      <i class="el-icon-select"></i> 确定
                    </el-button>
                  </div>
                </div>
              </div>
            </el-col>
          </el-row>
          
          <div v-if="recommendations.length === 0" class="no-recommendations">
            <el-empty description="没有找到匹配的推荐" :image-size="200">
              <template #description>
                <p>我们没有找到符合条件的推荐。请尝试调整筛选条件。</p>
              </template>
              <el-button type="primary" @click="resetFilters">重置筛选</el-button>
            </el-empty>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script>
import { ref, reactive, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { matchingService } from '../services/api'

export default {
  name: 'PairRecommendations',
  setup() {
    const route = useRoute()
    const userId1 = computed(() => route.params.userId1)
    const userId2 = computed(() => route.params.userId2)
    
    const loading = ref(true)
    const error = ref('')
    const recommendations = ref([])
    
    const filters = reactive({
      itemType: '',
      topK: 10
    })
    
    const fetchRecommendations = async () => {
      loading.value = true
      error.value = ''
      
      try {
        const response = await matchingService.getRecommendationsForPair(
          userId1.value,
          userId2.value,
          filters.itemType,
          filters.topK
        )
        
        recommendations.value = response.data.recommendations || []
      } catch (err) {
        console.error('获取推荐出错:', err)
        error.value = err.response?.data?.detail || '获取推荐失败，请稍后再试'
      } finally {
        loading.value = false
      }
    }
    
    const resetFilters = () => {
      filters.itemType = ''
      filters.topK = 10
      fetchRecommendations()
    }
    
    const recordInteraction = async (itemId, interactionType) => {
      try {
        // 这里可以调用API记录交互
        console.log(`记录交互: 用户 ${userId1.value} 对物品 ${itemId} 进行了 ${interactionType} 操作`)
        // 实际使用时调用交互记录API
      } catch (err) {
        console.error('记录交互出错:', err)
      }
    }
    
    const getDefaultImage = (type) => {
      const types = {
        'activity': '../assets/activity.svg',
        'travel': '../assets/travel.svg',
        'restaurant': '../assets/restaurant.svg',
        'movie': '../assets/movie.svg'
      }
      return types[type] || '../assets/default-recommendation.svg'
    }
    
    const getTagType = (type) => {
      const types = {
        'activity': '',
        'travel': 'success',
        'restaurant': 'warning',
        'movie': 'info'
      }
      return types[type] || ''
    }
    
    const getScoreColor = (score) => {
      if (score >= 0.7) return '#38b000'
      if (score >= 0.4) return '#ffb703'
      return '#d62828'
    }
    
    const truncateText = (text, maxLength) => {
      if (!text || text.length <= maxLength) return text
      return text.substring(0, maxLength) + '...'
    }
    
    const formatPrice = (price) => {
      if (typeof price === 'number') {
        return `¥${price.toFixed(2)}`
      }
      return price
    }
    
    onMounted(() => {
      fetchRecommendations()
    })
    
    return {
      userId1,
      userId2,
      loading,
      error,
      recommendations,
      filters,
      fetchRecommendations,
      resetFilters,
      recordInteraction,
      getDefaultImage,
      getTagType,
      getScoreColor,
      truncateText,
      formatPrice
    }
  }
}
</script>

<style scoped>
.pair-recommendations {
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

.user-pair-header {
  margin-bottom: 2rem;
  padding: 1.5rem;
}

.user-pair {
  display: flex;
  justify-content: center;
  align-items: center;
  margin-bottom: 1.5rem;
}

.user-info {
  text-align: center;
}

.user-avatar {
  margin-bottom: 0.5rem;
}

.user-avatar .avatar {
  width: 60px;
  height: 60px;
  border-radius: 50%;
  object-fit: cover;
  border: 3px solid white;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
}

.user-name {
  font-weight: 600;
}

.connection-indicator {
  position: relative;
  width: 100px;
  height: 40px;
  margin: 0 1rem;
}

.connection-line {
  position: absolute;
  top: 50%;
  left: 0;
  right: 0;
  height: 2px;
  background-color: var(--primary-color);
  transform: translateY(-50%);
  z-index: 1;
}

.connection-icon {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 40px;
  height: 40px;
  background-color: white;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  color: var(--primary-color);
  border: 2px solid var(--primary-color);
  z-index: 2;
}

.recommendation-filters {
  border-top: 1px solid var(--grey-color);
  padding-top: 1.5rem;
}

.filter-form {
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
}

.recommendations-list {
  margin-top: 2rem;
}

.recommendation-card {
  height: 100%;
  margin-bottom: 1.5rem;
  overflow: hidden;
}

.rec-image {
  height: 160px;
  overflow: hidden;
}

.rec-image img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.3s ease;
}

.recommendation-card:hover .rec-image img {
  transform: scale(1.05);
}

.rec-content {
  padding: 1.2rem;
}

.rec-title {
  margin-top: 0;
  margin-bottom: 0.5rem;
  font-size: 1.2rem;
}

.rec-type {
  margin-bottom: 0.75rem;
}

.rec-score {
  margin-bottom: 1rem;
}

.score-label {
  font-size: 0.85rem;
  color: #666;
  margin-bottom: 0.3rem;
}

.rec-description {
  font-size: 0.9rem;
  color: #444;
  margin-bottom: 1rem;
  line-height: 1.5;
}

.rec-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-bottom: 1rem;
  font-size: 0.85rem;
  color: #666;
}

.meta-item {
  display: flex;
  align-items: center;
}

.meta-item i {
  margin-right: 0.3rem;
}

.rec-tags {
  margin-bottom: 1rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.more-count {
  font-size: 0.8rem;
  color: #666;
  display: flex;
  align-items: center;
}

.rec-actions {
  display: flex;
  justify-content: space-between;
}

.no-recommendations {
  margin-top: 3rem;
}

@media (max-width: 768px) {
  .user-pair {
    flex-direction: column;
    gap: 1rem;
  }
  
  .connection-indicator {
    transform: rotate(90deg);
    margin: 1rem 0;
  }
  
  .filter-form {
    flex-direction: column;
  }
}
</style> 