import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
 plugins:[react()],
 define:{'process.env.NODE_ENV':JSON.stringify('production')},
 build:{outDir:'../../src/okama_planner/_journal_assets',emptyOutDir:true,
  lib:{entry:'src/main.jsx',formats:['es'],fileName:'journal',cssFileName:'journal'}}
});
