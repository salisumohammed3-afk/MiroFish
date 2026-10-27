<template>
  <!--
    Someone signed into the hub whose company does not have Forecast, or who
    is not on Forecast's People list. It names nobody, not even them.
  -->
  <main class="door">
    <div class="box">
      <h1>Not available yet</h1>
      <p>{{ NOT_IN_USE_MESSAGE }}</p>
      <div class="actions">
        <a :href="HUB" class="primary">Open the hub</a>
        <a :href="logout" class="secondary">Sign out</a>
      </div>
    </div>
  </main>
</template>

<script setup>
import { HUB, hubLogoutUrl, NOT_IN_USE_MESSAGE } from '../lib/hub'

const logout = hubLogoutUrl(`${window.location.origin}/`)
</script>

<style scoped>
.door {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px 16px;
  background: #ffffff;
  color: #0b1220;
  font-family: 'DM Sans', system-ui, -apple-system, sans-serif;
}
.box { max-width: 440px; text-align: center; }
h1 {
  font-family: 'Outfit', system-ui, -apple-system, sans-serif;
  font-weight: 700;
  letter-spacing: -0.03em;
  font-size: 28px;
  margin: 0;
}
p { font-size: 15px; color: #5b6472; margin: 12px 0 0; line-height: 1.6; }
.actions { margin-top: 24px; display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; }
.primary, .secondary {
  border-radius: 8px;
  padding: 8px 16px;
  font-size: 13.5px;
  font-weight: 600;
  text-decoration: none;
}
.primary { background: #0099ff; color: #ffffff; }
.secondary { border: 1px solid #e9edf3; color: #0b1220; }
</style>
