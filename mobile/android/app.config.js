// DISMEPE ONE Android: configuracao nativa. Sem credenciais de servidor.
const config = {
  name: 'DISMEPE ONE',
  slug: 'dismepe-one-mobile',
  owner: 'dantonmelo',
  scheme: 'dismepeone',
  version: '0.1.0',
  orientation: 'portrait',
  userInterfaceStyle: 'automatic',
  platforms: ['android'],
  android: {
    package: 'br.com.dismepe.dismepeone',
    // No EAS, configure GOOGLE_SERVICES_JSON como variavel de tipo arquivo.
    // Em compilacao local, use ./google-services.json (fora do Git).
    googleServicesFile: process.env.GOOGLE_SERVICES_JSON || './google-services.json',
    permissions: ['POST_NOTIFICATIONS']
  },
  plugins: ['expo-notifications']
};
module.exports = { expo: config };
