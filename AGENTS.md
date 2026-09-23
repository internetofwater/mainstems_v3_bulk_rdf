This project is a Geoconnex bulk integration for the mainstem dataset here: https://www.hydroshare.org/resource/3295a17b4cc24d34bd6a5c5aaf753c50/data/contents/mainstems_v3.gpkg

A general live JSON-LD example can be found here: https://reference.geoconnex.us/collections/mainstems/items/2290857?f=jsonld

The old JSON-LD template used for generating the JSON-LD data over the old gpkg can be found here: https://github.com/internetofwater/reference.geoconnex.us/blob/main/pygeoapi-skin-dashboard/templates/jsonld/mainstems/collections/items/item.jsonld

This integration should generate the same general JSON-LD RDF data but use the Geoconnex bulk loader method. It should publish a Docker image to Github that I can use to run the bulk integration.