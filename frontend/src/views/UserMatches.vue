<template>
  <div class="user-matches">
    <div class="container">
      <h1 class="page-title">用户匹配</h1>
      
      <div class="search-form card section">
        <el-form :model="searchForm" label-width="120px">
          <el-form-item label="用户ID">
            <el-input v-model="searchForm.userId" placeholder="输入用户ID"></el-input>
          </el-form-item>
          
          <el-form-item label="匹配数量">
            <el-slider v-model="searchForm.topK" :min="1" :max="50" :step="1" show-input></el-slider>
          </el-form-item>
          
          <el-form-item label="最小相似度">
            <el-slider v-model="searchForm.minSimilarity" :min="0" :max="1" :step="0.05" show-input></el-slider>
          </el-form-item>
          
          <el-form-item label="最小互补度">
            <el-slider v-model="searchForm.minComplementarity" :min="0" :max="1" :step="0.05" show-input></el-slider>
          </el-form-item>
          
          <el-form-item label="性别">
            <el-select v-model="searchForm.genderFilter" placeholder="选择性别">
              <el-option label="不限" value=""></el-option>
              <el-option label="男性" value="male"></el-option>
              <el-option label="女性" value="female"></el-option>
              <el-option label="其他" value="other"></el-option>
            </el-select>
          </el-form-item>
          
          <el-form-item>
            <el-button type="primary" @click="findMatches" :loading="loading">查找匹配</el-button>
            <el-button @click="resetForm">重置</el-button>
          </el-form-item>
        </el-form>
      </div>
      
      <div v-if="error" class="error-alert">
        <el-alert :title="error" type="error" :closable="false"></el-alert>
      </div>
      
      <div v-if="matches.length" class="matches-container">
        <h2 class="section-title">为 "{{ searchForm.userId }}" 找到 {{ matches.length }} 个匹配</h2>
        
        <el-row :gutter="20">
          <el-col v-for="match in matches" :key="match.user_id" :xs="24" :sm="12" :md="8" :lg="6">
            <div class="match-card card">
              <div class="match-header">
                <div class="match-avatar">
                  <img :src="match.avatar_url || '../assets/default-avatar.svg'" alt="用户头像" class="avatar">
                </div>
                <div class="match-info">
                  <h3>{{ match.name || `用户 ${match.user_id}` }}</h3>
                  <div class="match-location" v-if="match.location">
                    <i class="el-icon-location"></i> {{ match.location }}
                  </div>
                  <div class="match-age-gender" v-if="match.age || match.gender">
                    {{ match.age }}岁 · {{ formatGender(match.gender) }}
                  </div>
                </div>
              </div>
              
              <div class="match-scores">
                <div class="score-item">
                  <div class="score-label">匹配度</div>
                  <div class="score-value" :class="getScoreClass(match.match_score)">
                    {{ (match.match_score * 100).toFixed(0) }}%
                  </div>
                </div>
                <div class="score-item">
                  <div class="score-label">相似度</div>
                  <div class="score-value">
                    {{ (match.similarity * 100).toFixed(0) }}%
                  </div>
                </div>
                <div class="score-item">
                  <div class="score-label">互补度</div>
                  <div class="score-value">
                    {{ (match.complementarity * 100).toFixed(0) }}%
                  </div>
                </div>
              </div>
              
              <div class="match-interests" v-if="match.interests && match.interests.length">
                <div class="interests-label">兴趣爱好:</div>
                <div class="interests-tags">
                  <span v-for="(interest, idx) in match.interests.slice(0, 3)" :key="idx" class="tag">
                    {{ interest }}
                  </span>
                  <span v-if="match.interests.length > 3" class="more-tag">
                    +{{ match.interests.length - 3 }}
                  </span>
                </div>
              </div>
              
              <div class="match-bio" v-if="match.bio">
                {{ truncateText(match.bio, 100) }}
              </div>
              
              <div class="match-actions">
                <router-link :to="`/match-details/${searchForm.userId}/${match.user_id}`" class="btn btn-primary">
                  查看详情
                </router-link>
                <router-link :to="`/recommendations/${searchForm.userId}/${match.user_id}`" class="btn btn-secondary">
                  推荐活动
                </router-link>
              </div>
            </div>
          </el-col>
        </el-row>
      </div>
      
      <div v-else-if="!loading && !error && searched" class="no-results">
        <el-empty description="未找到匹配结果" :image-size="200">
          <template #description>
            <p>未找到符合条件的匹配用户。请尝试调整搜索条件。</p>
          </template>
        </el-empty>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, reactive } from 'vue'
import { matchingService } from '../services/api'

export default {
  name: 'UserMatches',
  setup() {
    const searchForm = reactive({
      userId: '',
      topK: 10,
      minSimilarity: 0.3,
      minComplementarity: 0.3,
      genderFilter: ''
    })
    
    const matches = ref([])
    const loading = ref(false)
    const error = ref('')
    const searched = ref(false)
    
    const findMatches = async () => {
      if (!searchForm.userId) {
        error.value = '请输入用户ID'
        return
      }
      
      loading.value = true
      error.value = ''
      
      try {
        const response = await matchingService.getPotentialMatches(
          searchForm.userId,
          searchForm.topK,
          searchForm.minSimilarity,
          searchForm.minComplementarity,
          searchForm.genderFilter || null
        )
        
        matches.value = response.data.matches || []
        searched.value = true
      } catch (err) {
        console.error('查找匹配出错:', err)
        error.value = err.response?.data?.detail || '获取匹配数据失败，请稍后再试'
      } finally {
        loading.value = false
      }
    }
    
    const resetForm = () => {
      searchForm.userId = ''
      searchForm.topK = 10
      searchForm.minSimilarity = 0.3
      searchForm.minComplementarity = 0.3
      searchForm.genderFilter = ''
      matches.value = []
      error.value = ''
      searched.value = false
    }
    
    const formatGender = (gender) => {
      if (!gender) return ''
      const genderMap = {
        'male': '男',
        'female': '女',
        'other': '其他'
      }
      return genderMap[gender.toLowerCase()] || gender
    }
    
    const getScoreClass = (score) => {
      if (score >= 0.7) return 'match-score-high'
      if (score >= 0.4) return 'match-score-medium'
      return 'match-score-low'
    }
    
    const truncateText = (text, maxLength) => {
      if (!text || text.length <= maxLength) return text
      return text.substring(0, maxLength) + '...'
    }
    
    return {
      searchForm,
      matches,
      loading,
      error,
      searched,
      findMatches,
      resetForm,
      formatGender,
      getScoreClass,
      truncateText
    }
  }
}
</script>

<style scoped>
.user-matches {
  padding-bottom: 3rem;
}

.page-title {
  margin-bottom: 1.5rem;
  color: var(--primary-color);
}

.search-form {
  margin-bottom: 2rem;
}

.matches-container {
  margin-top: 2rem;
}

.match-card {
  padding: 1.5rem;
  margin-bottom: 1.5rem;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.match-header {
  display: flex;
  margin-bottom: 1rem;
}

.match-avatar {
  margin-right: 1rem;
}

.match-avatar .avatar {
  width: 60px;
  height: 60px;
}

.match-info h3 {
  margin: 0 0 0.5rem 0;
  font-size: 1.2rem;
}

.match-location,
.match-age-gender {
  font-size: 0.9rem;
  color: #666;
  margin-bottom: 0.25rem;
}

.match-scores {
  display: flex;
  justify-content: space-between;
  margin-bottom: 1rem;
  padding: 0.5rem 0;
  border-top: 1px solid var(--grey-color);
  border-bottom: 1px solid var(--grey-color);
}

.score-item {
  text-align: center;
  flex: 1;
}

.score-label {
  font-size: 0.8rem;
  color: #666;
  margin-bottom: 0.3rem;
}

.score-value {
  font-weight: bold;
  font-size: 1.1rem;
}

.match-interests {
  margin-bottom: 1rem;
}

.interests-label {
  font-size: 0.9rem;
  color: #666;
  margin-bottom: 0.5rem;
}

.interests-tags {
  display: flex;
  flex-wrap: wrap;
}

.more-tag {
  font-size: 0.8rem;
  color: #666;
  display: inline-flex;
  align-items: center;
  padding: 0 0.5rem;
}

.match-bio {
  margin-bottom: 1rem;
  font-size: 0.9rem;
  color: #444;
  flex-grow: 1;
}

.match-actions {
  display: flex;
  gap: 0.5rem;
  margin-top: auto;
}

.match-actions .btn {
  flex: 1;
  text-align: center;
  text-decoration: none;
  padding: 0.5rem 1rem;
  font-size: 0.9rem;
}

.no-results {
  text-align: center;
  padding: 3rem 0;
}

.error-alert {
  margin-bottom: 1.5rem;
}
</style> 