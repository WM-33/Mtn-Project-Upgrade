import requests
from bs4 import BeautifulSoup
import json
import re
import time
from urllib.parse import urljoin, urlparse
import csv
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict

@dataclass
class Route:
    name: str
    difficulty: str
    description: str
    access_info: str
    user_ratings: List[Dict]
    location: Dict
    images: List[str]
    url: str

class MountainProjectScraper:
    def __init__(self, delay=1):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        self.delay = delay
        self.base_url = "https://www.mountainproject.com"
    
    def get_page(self, url):
        """Get page content with error handling and rate limiting"""
        try:
            time.sleep(self.delay)
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        except requests.RequestException as e:
            print(f"Error fetching {url}: {e}")
            return None
    
    def extract_route_basic_info(self, soup):
        """Extract basic route information"""
        route_info = {}
        
        # Route name
        name_elem = soup.find('h1')
        route_info['name'] = name_elem.get_text(strip=True) if name_elem else "N/A"
        
        # Difficulty/Grade
        grade_elem = soup.find('span', class_='rateYDS') or soup.find('span', class_='rateHueco') or soup.find('span', class_='rateVScale')
        if not grade_elem:
            grade_elem = soup.find('h2', class_='inline-block mr-2')
        route_info['difficulty'] = grade_elem.get_text(strip=True) if grade_elem else "N/A"
        
        return route_info
    
    def extract_description(self, soup):
        """Extract route description"""
        desc_section = soup.find('div', class_='fr-view') or soup.find('div', {'id': 'route-description'})
        if desc_section:
            # Remove any script tags or unwanted elements
            for script in desc_section(["script", "style"]):
                script.decompose()
            return desc_section.get_text(strip=True, separator=' ')
        return "No description available"
    
    def extract_access_info(self, soup):
        """Extract access and approach information"""
        access_info = []
        
        # Look for "Getting There" or "Access" sections
        access_headers = soup.find_all(['h3', 'h4', 'h5'], string=re.compile(r'(Getting There|Access|Approach)', re.I))
        
        for header in access_headers:
            next_elem = header.find_next_sibling()
            if next_elem and next_elem.name in ['p', 'div']:
                access_info.append(next_elem.get_text(strip=True))
        
        # Also check for dedicated access sections
        access_section = soup.find('div', {'id': 'route-getting-there'}) or soup.find('section', class_='getting-there')
        if access_section:
            access_info.append(access_section.get_text(strip=True, separator=' '))
        
        return ' '.join(access_info) if access_info else "No access information available"
    
    def extract_user_ratings(self, soup):
        """Extract user ratings and reviews"""
        ratings = []
        
        # Look for rating elements
        rating_elements = soup.find_all('div', class_='star-rating') + soup.find_all('span', class_='scoreStars')
        
        for rating_elem in rating_elements:
            rating_data = {}
            
            # Extract star rating
            stars = rating_elem.find_all('i', class_='fa-star') + rating_elem.find_all('span', class_='star')
            filled_stars = len([s for s in stars if 'filled' in s.get('class', []) or 'active' in s.get('class', [])])
            
            if filled_stars > 0:
                rating_data['stars'] = filled_stars
                
                # Try to find associated user and comment
                parent = rating_elem.find_parent()
                if parent:
                    user_elem = parent.find('a', href=re.compile(r'/user/'))
                    if user_elem:
                        rating_data['user'] = user_elem.get_text(strip=True)
                    
                    comment_elem = parent.find('div', class_='comment') or parent.find('p')
                    if comment_elem:
                        rating_data['comment'] = comment_elem.get_text(strip=True)
                
                ratings.append(rating_data)
        
        return ratings
    
    def extract_location(self, soup):
        """Extract physical location information"""
        location = {}
        
        # Look for coordinates
        coord_pattern = re.compile(r'(-?\d+\.?\d*),\s*(-?\d+\.?\d*)')
        
        # Check meta tags for coordinates
        for meta in soup.find_all('meta'):
            content = meta.get('content', '')
            if coord_pattern.search(content):
                match = coord_pattern.search(content)
                location['latitude'] = float(match.group(1))
                location['longitude'] = float(match.group(2))
                break
        
        # Look for location breadcrumbs
        breadcrumbs = soup.find('nav', class_='breadcrumbs') or soup.find('div', class_='breadcrumb')
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            location['area_hierarchy'] = [link.get_text(strip=True) for link in links if link.get_text(strip=True)]
        
        # Look for elevation
        elevation_elem = soup.find(string=re.compile(r'elevation', re.I))
        if elevation_elem:
            parent = elevation_elem.parent if elevation_elem.parent else elevation_elem
            elevation_text = parent.get_text() if hasattr(parent, 'get_text') else str(parent)
            elevation_match = re.search(r'(\d+)\s*(?:ft|feet|m|meters)', elevation_text, re.I)
            if elevation_match:
                location['elevation'] = elevation_match.group(1)
        
        return location
    
    def extract_images(self, soup, base_url):
        """Extract route images"""
        images = []
        
        # Look for various image containers
        img_selectors = [
            'img[src*="route"]',
            'img[src*="photo"]',
            '.photo img',
            '.image-gallery img',
            '#route-photos img'
        ]
        
        for selector in img_selectors:
            img_elements = soup.select(selector)
            for img in img_elements:
                src = img.get('src') or img.get('data-src')
                if src:
                    full_url = urljoin(base_url, src)
                    if full_url not in images:
                        images.append(full_url)
        
        return images
    
    def scrape_route(self, route_url):
        """Scrape a single route page"""
        print(f"Scraping route: {route_url}")
        soup = self.get_page(route_url)
        
        if not soup:
            return None
        
        try:
            # Extract all route information
            basic_info = self.extract_route_basic_info(soup)
            description = self.extract_description(soup)
            access_info = self.extract_access_info(soup)
            user_ratings = self.extract_user_ratings(soup)
            location = self.extract_location(soup)
            images = self.extract_images(soup, self.base_url)
            
            route = Route(
                name=basic_info.get('name', 'N/A'),
                difficulty=basic_info.get('difficulty', 'N/A'),
                description=description,
                access_info=access_info,
                user_ratings=user_ratings,
                location=location,
                images=images,
                url=route_url
            )
            
            return route
            
        except Exception as e:
            print(f"Error parsing route {route_url}: {e}")
            return None
    
    def find_routes_from_area(self, area_url, max_routes=None):
        """Find route URLs from an area page"""
        soup = self.get_page(area_url)
        if not soup:
            return []
        
        route_links = []
        
        # Look for route links
        for link in soup.find_all('a', href=True):
            href = link['href']
            if '/route/' in href:
                full_url = urljoin(self.base_url, href)
                route_links.append(full_url)
        
        # Remove duplicates
        route_links = list(set(route_links))
        
        if max_routes:
            route_links = route_links[:max_routes]
        
        return route_links
    
    def scrape_multiple_routes(self, route_urls):
        """Scrape multiple routes"""
        routes = []
        
        for url in route_urls:
            route = self.scrape_route(url)
            if route:
                routes.append(route)
        
        return routes
    
    def save_to_json(self, routes, filename='mountain_project_routes.json'):
        """Save routes to JSON file"""
        routes_dict = [asdict(route) for route in routes]
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(routes_dict, f, indent=2, ensure_ascii=False)
        print(f"Saved {len(routes)} routes to {filename}")
    
    def save_to_csv(self, routes, filename='mountain_project_routes.csv'):
        """Save routes to CSV file"""
        if not routes:
            return
        
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['name', 'difficulty', 'description', 'access_info', 
                         'rating_count', 'avg_rating', 'location_area', 
                         'latitude', 'longitude', 'elevation', 'image_count', 'url']
            
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for route in routes:
                # Process ratings
                ratings = route.user_ratings
                avg_rating = sum(r.get('stars', 0) for r in ratings) / len(ratings) if ratings else 0
                
                # Process location
                location_area = ', '.join(route.location.get('area_hierarchy', []))
                
                row = {
                    'name': route.name,
                    'difficulty': route.difficulty,
                    'description': route.description[:500] + '...' if len(route.description) > 500 else route.description,
                    'access_info': route.access_info[:300] + '...' if len(route.access_info) > 300 else route.access_info,
                    'rating_count': len(ratings),
                    'avg_rating': round(avg_rating, 1) if avg_rating > 0 else 'N/A',
                    'location_area': location_area,
                    'latitude': route.location.get('latitude', 'N/A'),
                    'longitude': route.location.get('longitude', 'N/A'),
                    'elevation': route.location.get('elevation', 'N/A'),
                    'image_count': len(route.images),
                    'url': route.url
                }
                writer.writerow(row)
        
        print(f"Saved {len(routes)} routes to {filename}")

# Example usage
def main():
    scraper = MountainProjectScraper(delay=1)
    
    # Option 1: Scrape specific route URLs
    route_urls = [
        "https://www.mountainproject.com/route/105748391/the-nose",
        "https://www.mountainproject.com/route/105924807/freerider"
    ]
    
    routes = scraper.scrape_multiple_routes(route_urls)
    
    # Option 2: Find routes from an area and scrape them
    # area_url = "https://www.mountainproject.com/area/105833381/yosemite-valley"
    # route_urls = scraper.find_routes_from_area(area_url, max_routes=10)
    # routes = scraper.scrape_multiple_routes(route_urls)
    
    # Save results
    if routes:
        scraper.save_to_json(routes)
        scraper.save_to_csv(routes)
        
        # Print summary
        print(f"\nScraping Summary:")
        print(f"Total routes scraped: {len(routes)}")
        for route in routes:
            print(f"- {route.name} ({route.difficulty})")
            print(f"  Location: {', '.join(route.location.get('area_hierarchy', ['Unknown']))}")
            print(f"  Ratings: {len(route.user_ratings)} user ratings")
            print(f"  Images: {len(route.images)} images")
            print()

if __name__ == "__main__":
    main()