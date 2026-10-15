import { createApp } from 'vue'
import App from './App.vue'
import Watch from './Watch.vue'
import Monitor from './Monitor.vue'
import Attention from './Attention.vue'
import './style.css'
const path = window.location.pathname.replace(/\/$/, '')
createApp(path === '/crawler-watch/attention' ? Attention : path === '/crawler-watch/updates' ? Monitor : path === '/crawler-watch' ? Watch : App).mount('#app')
