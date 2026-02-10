const axios = require('axios');

const fetchRecipes = async (query) => {
  const YOUR_APP_ID = 'db4a5dcf';
  const YOUR_APP_KEY = '403f097b72b83210e0407adbd29f300a';

  try {
    const response = await axios.get(`https://api.edamam.com/search?q=${query}&app_id=${YOUR_APP_ID}&app_key=${YOUR_APP_KEY}`);
    return response.data.hits; // Hits contains an array of recipe objects
  } catch (error) {
    console.error('Error fetching recipes:', error);
    return []; // Return an empty array if there's an error
  }
};

// Example usage:
const query = 'chicken';
fetchRecipes(query)
  .then(recipes => {
    console.log('Recipes:', recipes);
  })
  .catch(error => {
    console.error('Error:', error);
  });
  