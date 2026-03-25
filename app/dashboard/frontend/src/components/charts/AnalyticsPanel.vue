<script setup lang="ts">
import BiasDispositionCard from './BiasDispositionCard.vue'
import BiasOverconfidenceCard from './BiasOverconfidenceCard.vue'
import BiasLotteryCard from './BiasLotteryCard.vue'
import BiasUnderdiversificationCard from './BiasUnderdiversificationCard.vue'
import BiasHerdingCard from './BiasHerdingCard.vue'
import BiasBubbleCard from './BiasBubbleCard.vue'
import PolarizationPanel from './PolarizationPanel.vue'
import CascadePanel from './CascadePanel.vue'
import TradeFreqPanel from './TradeFreqPanel.vue'
import LiquidityPanel from './LiquidityPanel.vue'
import LossAversionPanel from './LossAversionPanel.vue'
import PlanExecutionPanel from './PlanExecutionPanel.vue'
import MarketMakerPanel from './MarketMakerPanel.vue'
</script>

<template>
  <div class="analytics-grid">
    <BiasDispositionCard />
    <BiasOverconfidenceCard />
    <BiasLotteryCard />
    <BiasUnderdiversificationCard />
    <BiasHerdingCard />
    <BiasBubbleCard />
    <LossAversionPanel />
    <PolarizationPanel />
    <CascadePanel />
    <TradeFreqPanel />
    <LiquidityPanel />
    <PlanExecutionPanel />
    <MarketMakerPanel />
  </div>
</template>

<style scoped>
.analytics-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

@media (max-width: 1200px) {
  .analytics-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .analytics-grid {
    grid-template-columns: 1fr;
  }
}
</style>
