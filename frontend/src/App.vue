<template>
  <router-view />
</template>

<script setup>
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

#app {
  font-family: 'DM Sans', system-ui, -apple-system, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: #0b1220;
  background-color: #ffffff;
}

::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: #f1f1f1;
}

::-webkit-scrollbar-thumb {
  background: #0099ff;
  border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
  background: #0099ff;
}

button {
  font-family: inherit;
}

h1, h2, h3, h4 {
  font-family: 'Outfit', system-ui, sans-serif;
  letter-spacing: -0.02em;
}
</style>
