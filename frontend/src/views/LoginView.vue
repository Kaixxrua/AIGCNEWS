<script setup lang="ts">
import { useRoute } from 'vue-router'
import LoginForm from '@/components/auth/LoginForm.vue'
const route = useRoute()
</script>

<template>
  <div class="flex h-full items-center justify-center p-3 sm:p-6">
    <LoginForm :redirect="route.query.redirect" />
  </div>
</template>
