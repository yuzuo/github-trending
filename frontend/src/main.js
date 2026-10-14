import { createApp } from 'vue'
import App from './App.vue'
import Watch from './Watch.vue'
import './style.css'
createApp(window.location.pathname.replace(/\/$/, '') === '/crawler-watch' ? Watch : App).mount('#app')
