import { createApp } from 'vue'
import { ElDatePicker, ElOption, ElSelect, ElSwitch, ElTabPane, ElTabs } from 'element-plus'
import router from './router'
import App from './App.vue'
import 'element-plus/es/components/date-picker/style/css'
import 'element-plus/es/components/option/style/css'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/switch/style/css'
import 'element-plus/es/components/tab-pane/style/css'
import 'element-plus/es/components/tabs/style/css'
import './style.css'

createApp(App)
  .use(router)
  .use(ElSelect)
  .use(ElOption)
  .use(ElSwitch)
  .use(ElDatePicker)
  .use(ElTabs)
  .use(ElTabPane)
  .mount('#app')
