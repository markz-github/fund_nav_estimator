import { createApp } from 'vue'
import { ElOption, ElSelect } from 'element-plus'
import router from './router'
import App from './App.vue'
import 'element-plus/es/components/option/style/css'
import 'element-plus/es/components/select/style/css'
import './style.css'

createApp(App).use(router).use(ElSelect).use(ElOption).mount('#app')
