<script setup lang="ts">
import { RouterView } from 'vue-router'
</script>

<template>
  <!-- ═══ Layer -10: 暖调米白纸张底色 ═══ -->
  <div
    class="fixed inset-0 pointer-events-none bg-[#F7F5EE]"
    style="z-index: -10"
    aria-hidden="true"
  ></div>

  <!-- ═══ Layer -8: 极弱纸张噪点 ═══ -->
  <div
    class="fixed inset-0 pointer-events-none"
    style="z-index: -8; opacity: 0.025; mix-blend-mode: multiply; background-image: url('data:image/svg+xml,%3Csvg viewBox=%220 0 256 256%22 xmlns=%22http://www.w3.org/2000/svg%22%3E%3Cfilter id=%22n%22%3E%3CfeTurbulence type=%22fractalNoise%22 baseFrequency=%220.75%22 numOctaves=%224%22 stitchTiles=%22stitch%22/%3E%3C/filter%3E%3Crect width=%22100%25%22 height=%22100%25%22 filter=%22url(%23n)%22/%3E%3C/svg%3E'); background-repeat: repeat; background-size: 256px 256px;"
    aria-hidden="true"
  ></div>

  <!-- ═══ 顶层路由出口（Layout 或 Login/Register） ═══ -->
  <RouterView />
</template>
