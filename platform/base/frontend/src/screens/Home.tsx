import { HomePage } from '../framework';

export const meta = { title: '홈', icon: 'home' };

/** The home page belongs to the framework (search, favourites, recent programs); see framework/workspace/HomePage.tsx. */
export default function Home() {
  return <HomePage />;
}
