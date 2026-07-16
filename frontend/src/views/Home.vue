<template>
  <div class="home-page">
    <section class="hero">
      <div class="container">
        <div class="hero-content">
          <h1>找到最适合你的匹配</h1>
          <p>基于AI智能算法，分析你的兴趣和偏好，提供最精准的匹配推荐</p>
          <router-link to="/matches" class="btn btn-primary">开始匹配</router-link>
        </div>
        <div class="hero-image">
          <img src="../assets/hero-image.svg" alt="匹配图示" />
        </div>
      </div>
    </section>

    <section class="features">
      <div class="container">
        <h2 class="section-title text-center">我们的特色</h2>
        <div class="feature-grid">
          <div class="feature-card card">
            <div class="feature-icon">
              <i class="el-icon-data-analysis"></i>
            </div>
            <h3>智能匹配</h3>
            <p>利用先进的算法，根据相似度和互补性为你找到最优匹配</p>
          </div>
          
          <div class="feature-card card">
            <div class="feature-icon">
              <i class="el-icon-pie-chart"></i>
            </div>
            <h3>兴趣分析</h3>
            <p>深入分析你的兴趣爱好，发现与你有共同话题的人</p>
          </div>
          
          <div class="feature-card card">
            <div class="feature-icon">
              <i class="el-icon-magic-stick"></i>
            </div>
            <h3>个性化推荐</h3>
            <p>为你和匹配对象提供专属活动和内容推荐</p>
          </div>
          
          <div class="feature-card card">
            <div class="feature-icon">
              <i class="el-icon-connection"></i>
            </div>
            <h3>关系兼容性</h3>
            <p>全面评估关系兼容性，帮助你找到真正合适的伙伴</p>
          </div>
        </div>
      </div>
    </section>

    <section class="how-it-works">
      <div class="container">
        <h2 class="section-title text-center">如何使用</h2>
        <div class="steps">
          <div class="step">
            <div class="step-number">1</div>
            <h3>创建个人资料</h3>
            <p>填写你的基本信息、兴趣和偏好</p>
          </div>
          
          <div class="step">
            <div class="step-number">2</div>
            <h3>浏览潜在匹配</h3>
            <p>查看系统为你推荐的潜在匹配对象</p>
          </div>
          
          <div class="step">
            <div class="step-number">3</div>
            <h3>了解匹配详情</h3>
            <p>查看匹配度、共同兴趣和推荐活动</p>
          </div>
          
          <div class="step">
            <div class="step-number">4</div>
            <h3>建立联系</h3>
            <p>与你感兴趣的匹配对象开始交流</p>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script>
export default {
  name: 'HomePage'
}
</script>

<style scoped>
.home-page {
  padding-bottom: 3rem;
}

.hero {
  padding: 4rem 0;
  background: linear-gradient(135deg, var(--primary-color) 0%, var(--secondary-color) 100%);
  color: white;
  margin-bottom: 3rem;
}

.hero .container {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 2rem;
  align-items: center;
}

.hero-content h1 {
  font-size: 2.5rem;
  margin-bottom: 1.5rem;
}

.hero-content p {
  font-size: 1.2rem;
  margin-bottom: 2rem;
  opacity: 0.9;
}

.hero-image img {
  max-width: 100%;
  animation: float 6s ease-in-out infinite;
}

@keyframes float {
  0% {
    transform: translateY(0px);
  }
  50% {
    transform: translateY(-20px);
  }
  100% {
    transform: translateY(0px);
  }
}

.text-center {
  text-align: center;
}

.feature-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 2rem;
  margin-top: 3rem;
}

.feature-card {
  padding: 2rem;
  text-align: center;
  transition: all 0.3s ease;
}

.feature-icon {
  font-size: 2.5rem;
  color: var(--primary-color);
  margin-bottom: 1.5rem;
}

.feature-card h3 {
  margin-bottom: 1rem;
  font-size: 1.25rem;
}

.steps {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 2rem;
  margin-top: 3rem;
}

.step {
  text-align: center;
  position: relative;
}

.step-number {
  width: 50px;
  height: 50px;
  background-color: var(--primary-color);
  color: white;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.5rem;
  font-weight: bold;
  margin: 0 auto 1.5rem;
}

.step h3 {
  margin-bottom: 0.75rem;
}

/* 响应式调整 */
@media (max-width: 768px) {
  .hero .container {
    grid-template-columns: 1fr;
  }
  
  .hero-image {
    order: -1;
  }
  
  .hero-content {
    text-align: center;
  }
}
</style> 